import json

import django_redis
from celery import shared_task
from datetime import datetime, timedelta
from .models import SeckillProduct, SeckillOrder
from django.utils import timezone
from django.db.models import F


@shared_task
def update_seckill_status():
    """
    定时更新秒杀商品状态
    根据当前时间与商品的秒杀开始/结束时间比较，更新商品状态
    同时更新数据库和Redis中的商品状态
    """
    # 获取当前时间
    now = timezone.now()
    
    # 获取Redis客户端
    redis_client = django_redis.get_redis_connection("default")

    # 更新状态：秒杀开始（未开始 -> 进行中）
    started_products = SeckillProduct.objects.filter(
        status=0,  # 未开始
        seckill_start_time__lte=now  # 开始时间已到
    )
    # 在update前先获取需要更新的商品ID列表
    product_ids = list(started_products.values_list('id', flat=True))
    # 执行数据库更新
    started_count = started_products.update(status=1)
    
    # 更新Redis中的状态
    for product_id in product_ids:
        product_key = f"seckill:product:{product_id}"
        if redis_client.exists(product_key):
            redis_client.hset(product_key, "status", 1)

    # 更新状态：秒杀结束（进行中 -> 已结束）
    ended_products = SeckillProduct.objects.filter(
        status=1,  # 进行中
        seckill_end_time__lt=now  # 结束时间已过
    )
    # 在update前先获取需要更新的商品ID列表
    ended_product_ids = list(ended_products.values_list('id', flat=True))
    # 执行数据库更新
    ended_count = ended_products.update(status=2)
    
    # 更新Redis中的状态
    for product_id in ended_product_ids:
        product_key = f"seckill:product:{product_id}"
        if redis_client.exists(product_key):
            redis_client.hset(product_key, "status", 2)

    # 更新状态：过期未开始（未开始 -> 已结束）
    expired_products = SeckillProduct.objects.filter(
        status=0,  # 未开始
        seckill_end_time__lt=now  # 结束时间已过
    )
    # 在update前先获取需要更新的商品ID列表
    expired_product_ids = list(expired_products.values_list('id', flat=True))
    # 执行数据库更新
    expired_count = expired_products.update(status=2)
    
    # 更新Redis中的状态
    for product_id in expired_product_ids:
        product_key = f"seckill:product:{product_id}"
        if redis_client.exists(product_key):
            redis_client.hset(product_key, "status", 2)

    return {
        "message": "秒杀状态更新完成",
        "started_count": started_count,
        "ended_count": ended_count,
        "expired_count": expired_count
    }


@shared_task
def preheat_seckill_products():
    """
    秒杀商品预热任务
    在每场秒杀开始前5分钟将商品信息和库存加载到Redis缓存中
    """
    try:
        # 获取Redis客户端
        redis_client = django_redis.get_redis_connection("default")
        now = timezone.now()

        # 计算5分钟后的时间
        future_time = now + timedelta(minutes=5)

        # 获取所有未开始但将在5分钟内开始的秒杀商品
        preheat_products = SeckillProduct.objects.filter(
            status=0,  # 未开始
            seckill_start_time__lte=future_time,  # 5分钟内开始
        )

        # 预热商品信息到Redis
        for product in preheat_products:
            # 获取商品开始时间的小时数作为场次
            slot_hour = product.seckill_start_time.hour
            # 生成该场次的商品集合键
            slot_products_key = f"seckill:slot:{slot_hour}:products"

            # 缓存商品基本信息
            product_key = f"seckill:product:{product.id}"
            product_data = {
                "id": product.id,
                "name": product.name,
                "seckill_price": str(product.seckill_price),
                "base_price": str(product.base_price),
                "stock": product.stock,
                "status": product.status,
                "seckill_start_time": product.seckill_start_time.isoformat() if product.seckill_start_time else "",
                "seckill_end_time": product.seckill_end_time.isoformat() if product.seckill_end_time else ""
            }
            redis_client.hset(product_key, mapping=product_data)

            # 设置过期时间为该场次结束后半小时
            expire_seconds = int((product.seckill_end_time - now).total_seconds() + 1800)
            redis_client.expire(product_key, max(expire_seconds, 60))  # 至少缓存1分钟

            # 将商品ID添加到场次集合中
            redis_client.sadd(slot_products_key, product.id)
            redis_client.expire(slot_products_key, expire_seconds)

            print(f"已预热商品: {product.name}, ID: {product.id}, 开始时间: {product.seckill_start_time}")

        return f"成功预热{len(preheat_products)}个商品"

    except Exception as e:
        print(f"预热商品失败: {e}")
        return f"预热失败: {str(e)}"


@shared_task(bind=True, max_retries=3)
def create_seckill_order(self, message):
    """
    从RabbitMQ拉取消息，异步创建秒杀订单
    包含秒杀令牌验证和乐观锁防超卖
    """
    try:
        # 解包消息内容
        order_id = message['order_id']
        user_id = message['user_id']
        product_id = message['product_id']
        seckill_token = message['seckill_token']
        product_info = message['product_info']

        # 1. 验证秒杀令牌
        redis_client = django_redis.get_redis_connection("default")
        token_key = f"seckill:token:{seckill_token}"
        token_data = redis_client.get(token_key)

        if not token_data:
            raise ValueError(f"无效或过期的秒杀令牌: {seckill_token}")

        token_info = json.loads(token_data)
        # 验证令牌中的用户ID和商品ID是否匹配
        if token_info['user_id'] != user_id or token_info['product_id'] != product_id:
            raise ValueError(f"秒杀令牌验证失败: 用户ID或商品ID不匹配")

        # 验证通过后删除令牌，防止重复使用
        redis_client.delete(token_key)

        # 2. 使用乐观锁更新数据库库存并创建订单
        # 获取商品信息并检查库存
        product = SeckillProduct.objects.get(id=product_id)

        # 乐观锁实现：检查库存是否足够，足够则更新
        if product.stock > 0:
            # 使用F表达式和update_fields实现乐观锁
            # 只有当stock大于0且在update期间未被其他进程修改时才会成功
            updated_count = SeckillProduct.objects.filter(
                id=product_id,
                stock__gt=0  # 确保库存大于0
            ).update(
                stock=F('stock') - 1,
                update_time=timezone.now()
            )

            # 检查更新是否成功
            if updated_count == 0:
                # 乐观锁失败，说明库存已被其他请求消耗
                # 回滚Redis中的库存
                redis_client.incr(f"seckill:stock:{product_id}")
                raise ValueError(f"乐观锁失败，库存已不足: {product_id}")

            # 3. 创建订单
            order = SeckillOrder(
                id=order_id,
                user_id=user_id,
                goods_id=product_id,
                goods_name=product_info["name"],
                seckill_price=product_info["seckill_price"],
                quantity=1,
                total_amount=product_info["seckill_price"],
                status=0  # 待支付
            )
            order.save()

            print(f"订单创建成功: {order_id}, 商品: {product_info['name']}")
            
            # 发送延迟消息到RabbitMQ，5分钟后检查订单状态
            order_timeout_check.apply_async(
                args=[order_id, product_id, user_id],
                countdown=300  # 5分钟后执行
            )
            
            return f"订单创建成功: {order_id}"
        else:
            # 库存不足，回滚Redis中的库存
            redis_client.incr(f"seckill:stock:{product_id}")
            raise ValueError(f"库存不足，无法创建订单: {product_id}")

    except SeckillProduct.DoesNotExist:
        raise ValueError(f"商品不存在: {product_id}")
    except Exception as e:
        # 失败重试（最多3次）
        if self.request.retries < self.max_retries:
            print(f"订单创建失败，将重试: {order_id}, 错误: {str(e)}")
            return self.retry(exc=e, countdown=2)
        # 重试失败后回滚库存
        try:
            redis_client = django_redis.get_redis_connection("default")
            redis_client.incr(f"seckill:stock:{product_id}")
            print(f"重试失败，已回滚库存: {product_id}")
        except Exception as rollback_error:
            print(f"回滚库存失败: {rollback_error}")
        raise e


def restore_stock_and_remove_limit(product_id, user_id):
    """
    恢复商品库存并解除用户限购限制
    """
    try:
        redis_client = django_redis.get_redis_connection("default")
        
        # 1. 恢复Redis中的库存
        redis_client.incr(f"seckill:stock:{product_id}")
        current_stock = int(redis_client.get(f"seckill:stock:{product_id}"))
        product_key = f"seckill:product:{product_id}"
        redis_client.hset(product_key, "stock", current_stock)

        # 2. 恢复数据库中的库存
        SeckillProduct.objects.filter(id=product_id).update(
            stock=F('stock') + 1,
            update_time=timezone.now()
        )
        
        # 3. 解除用户限购限制（从用户集合中移除）
        user_limit_key = f"seckill:user_limit:{product_id}"
        redis_client.srem(user_limit_key, user_id)
        
        print(f"已恢复商品库存并解除限购: 商品ID={product_id}, 用户ID={user_id}")
        return True
    except Exception as e:
        print(f"恢复库存和解除限购失败: {str(e)}")
        return False


@shared_task(bind=True, max_retries=3)
def order_timeout_check(self, order_id, product_id, user_id):
    """
    检查订单是否超时未支付，如超时则取消订单并恢复库存
    """
    try:
        # 查询订单
        order = SeckillOrder.objects.get(id=order_id)
        
        # 检查订单状态，如果仍为待支付状态，则取消订单
        if order.status == 0:  # 0表示待支付
            # 更新订单状态为已取消
            order.status = 2  # 2表示已取消
            order.cancel_time = timezone.now()
            order.save()
            
            # 恢复库存并解除限购
            restore_stock_and_remove_limit(product_id, user_id)
            
            print(f"订单超时未支付，已自动取消: {order_id}")
            return f"订单超时自动取消成功: {order_id}"
        else:
            # 订单状态已变更（可能已支付或已取消），无需处理
            print(f"订单状态已变更，无需处理: {order_id}, 当前状态: {order.status}")
            return f"订单状态已变更，无需处理: {order_id}"
            
    except SeckillOrder.DoesNotExist:
        print(f"订单不存在: {order_id}")
        return f"订单不存在: {order_id}"
    except Exception as e:
        # 失败重试（最多3次）
        if self.request.retries < self.max_retries:
            print(f"订单超时检查失败，将重试: {order_id}, 错误: {str(e)}")
            return self.retry(exc=e, countdown=5)
        print(f"订单超时检查重试失败: {order_id}, 错误: {str(e)}")
        raise e
