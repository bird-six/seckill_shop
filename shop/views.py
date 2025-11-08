import hashlib
import json
import logging
import time
import django_redis
from alipay.aop.api.util.SignatureUtils import verify_with_rsa
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from seckill_shop import settings
from shop.models import SeckillProduct, SeckillOrder
from utils.bloom import BloomFilter
from utils.current_slot import get_current_slot
from datetime import datetime, timedelta
from django.utils import timezone
from utils.lua import STOCK_DECR_SCRIPT
from utils.rate_limit import sliding_window_limit
from utils.snow_flake import Snowflake
from utils.alipay import create_alipay_client, create_url, get_dic_sorted_params
from .tasks import create_seckill_order, restore_stock_and_remove_limit


# 获取Redis客户端实例
redis_client = django_redis.get_redis_connection("default")
# 初始化布隆过滤器（用于商品ID验证）
product_bloom = BloomFilter(key="seckill:bloom:product")
# 初始化雪花算法（用于订单ID生成）
snowflake = Snowflake(data_center_id=1, worker_id=1)
# 初始化支付宝客户端
alipay_client = create_alipay_client()


def init_bloom_filter():
    """初始化布隆过滤器，加载所有商品ID"""
    product_ids = SeckillProduct.objects.values_list('id', flat=True)
    product_bloom.batch_add(product_ids)

@sliding_window_limit(threshold=5)
def index(request):
    time_slots = [8, 10, 12, 14, 16, 18, 20, 22]

    current_slot = get_current_slot(datetime.now().hour)
    # 判断用户点击场次
    slot_param = request.GET.get('slot')
    if slot_param:
        selected_slot = int(slot_param)
    else:
        selected_slot = current_slot

    # 场次商品集合键
    slot_products_key = f"seckill:slot:{selected_slot}:products"
    # 从Redis中获取当前场次的商品ID集合
    product_ids = redis_client.smembers(slot_products_key)

    seckill_products = []

    # 如果redis中存在商品
    if product_ids:

        # 从redis中获取商品详情
        for product_id in product_ids:
            # 商品键
            product_key = f"seckill:product:{product_id.decode()}"
            product_data = redis_client.hgetall(product_key)
            if product_data:
                # 将字节数据转换为Python对象
                stock = int(product_data[b'stock'].decode())
                # 获取总库存（初始库存）
                total_stock = int(product_data.get(b'total_stock', product_data[b'stock']).decode())
                # 计算已售百分比
                sold_percentage = 0
                if total_stock > 0:
                    sold_percentage = min(100, round((total_stock - stock) / total_stock * 100))
                
                product_info = {
                    'id': int(product_data[b'id'].decode()),
                    'name': product_data[b'name'].decode(),
                    'seckill_price': float(product_data[b'seckill_price'].decode()),
                    'base_price': float(product_data[b'base_price'].decode()),
                    'stock': stock,
                    'total_stock': total_stock,
                    'sold_percentage': sold_percentage,
                    'status': int(product_data[b'status'].decode()),
                    'image': '/product_img/扫地机器人.webp',  # 默认图片
                    'seckill_start_time': datetime.fromisoformat(product_data[b'seckill_start_time'].decode()),
                    'seckill_end_time': datetime.fromisoformat(product_data[b'seckill_end_time'].decode())
                }
                seckill_products.append(product_info)
    else:
        # Redis中没有缓存，从数据库获取并缓存
        now = datetime.now()
        start_time = timezone.make_aware(datetime(now.year, now.month, now.day, selected_slot, 0, 0))
        db_products = SeckillProduct.objects.filter(seckill_start_time=start_time)

        # 将数据库商品添加到列表并缓存到Redis
        for product in db_products:
            # 为每个商品添加销售进度信息
            product.total_stock = product.stock  # 初始库存等于当前库存
            product.sold_percentage = 0  # 初始已售百分比为0
            seckill_products.append(product)
            # 缓存商品信息到Redis
            product_key = f"seckill:product:{product.id}"
            product_data = {
                "id": product.id,
                "name": product.name,
                "seckill_price": str(product.seckill_price),
                "base_price": str(product.base_price),
                "stock": product.stock,
                "total_stock": product.stock,  # 保存初始库存用于计算销售进度
                "status": product.status,
                "seckill_start_time": product.seckill_start_time.isoformat() if product.seckill_start_time else "",
                "seckill_end_time": product.seckill_end_time.isoformat() if product.seckill_end_time else ""
            }
            redis_client.hset(product_key, mapping=product_data)
            # 为商品键设置2.5小时过期时间
            redis_client.expire(product_key, 9000)

            # 缓存库存键
            stock_key = f"seckill:stock:{product.id}"
            redis_client.set(stock_key, product.stock)
            redis_client.expire(stock_key, 9000)

            # 将商品ID添加到场次集合中
            redis_client.sadd(slot_products_key, product.id)

        # 设置场次商品集合的过期时间为2.5小时
        redis_client.expire(slot_products_key, 9000)

    return render(request, "index.html", {
        "seckill_products": seckill_products,
        "time_slots": time_slots,
        "selected_slot": selected_slot
    })

@sliding_window_limit(threshold=5)
def buy(request, product_id):
    if request.method != "POST":
        return render(request, "result.html", {"code": 405, "msg": "方法不允许"})

    # 初始化布隆过滤器
    init_bloom_filter()

    # 验证商品ID是否存在
    if not product_bloom.contains(product_id):
        return render(request, "result.html", {"code": 404, "msg": "商品不存在"})

    # 获取用户ip标识用于购物限量
    user_id = request.META.get('HTTP_X_FORWARDED_FOR', '127.0.0.1')
    if not user_id:
        return render(request, "result.html", {"code": 400, "msg": "用户标识获取失败"})

    product_key = f"seckill:product:{product_id}"   # 商品键
    stock_key = f"seckill:stock:{product_id}"    # 库存键
    user_limit_key = f"seckill:user_limit:{product_id}"  # 记录已购买用户
    result_key = f"seckill:result:{user_id}:{product_id}"  # 秒杀结果缓存

    # 检查商品状态
    try:
        # 从Redis获取状态
        status = redis_client.hget(product_key, "status")
        if status is None:
            # 如果Redis中没有找到状态，可能是商品不存在或者缓存过期
            return render(request, "result.html", {"code": 404, "msg": "商品不存在或已下架"})

        if int(status) != 1:
            return render(request, "result.html", {"code": 400, "msg": "秒杀未开始或已结束"})
    except SeckillProduct.DoesNotExist:
        return render(request, "result.html", {"code": 404, "msg": "商品不存在"})

    # 执行Lua脚本，检查并扣减库存
    try:
        # 执行Lua脚本
        result = redis_client.eval(
            STOCK_DECR_SCRIPT,
            3,  # 键的数量
            stock_key, product_key, user_limit_key,  # 三个KEYS参数
            user_id  # ARGV参数
        )

        # 秒杀成功
        if result == 1:
            # 生成秒杀令牌
            timestamp = int(time.time() * 1000)
            token_data = f"{user_id}:{product_id}:{timestamp}:{settings.SECRET_KEY}"
            seckill_token = hashlib.md5(token_data.encode()).hexdigest()

            # 缓存秒杀令牌，用于订单创建时验证
            token_key = f"seckill:token:{seckill_token}"
            token_value = json.dumps({
                "user_id": user_id,
                "product_id": product_id,
                "timestamp": timestamp
            })
            redis_client.setex(token_key, 300, token_value)  # 令牌5分钟内有效

            # 生成唯一订单ID
            order_id = snowflake.generate_id()

            # 获取商品信息
            product_data = redis_client.hgetall(product_key)
            product_info = {
                "id": product_id,
                "name": product_data[b"name"].decode(),
                "seckill_price": float(product_data[b"seckill_price"].decode())
            }

            # 创建消息内容，包含用户ID、商品ID、秒杀令牌
            message = {
                "order_id": order_id,
                "user_id": user_id,
                "product_id": product_id,
                "seckill_token": seckill_token,
                "product_info": product_info
            }

            # 调用Celery异步任务，通过RabbitMQ发送消息
            create_seckill_order.delay(message=message)

            # 记录秒杀结果（供前端轮询）
            redis_client.setex(result_key, 300, json.dumps({
                "success": True,
                "order_id": order_id
            }))

            return render(request, "result.html", {
                "code": 200,
                "msg": "抢购成功，正在生成订单...",
                "order_id": order_id
            })
        # 库存不足
        elif result == 0:
            redis_client.setex(result_key, 60, json.dumps({"success": False, "msg": "商品已抢完"}))
            return render(request, "result.html", {"code": 400, "msg": "商品已抢完"})

        # 用户已购买
        elif result == 2:
            return render(request, "result.html", {"code": 400, "msg": "您已购买过该商品"})

    except Exception as e:
        return render(request, "result.html", {"code": 500, "msg": f"系统错误：{str(e)}"})

@sliding_window_limit(threshold=5)
def order_list(request):
    """订单列表页面"""
    # 获取用户标识
    user_id = request.META.get('HTTP_X_FORWARDED_FOR', '127.0.0.1')
    
    # 查询该用户的所有订单，按创建时间倒序排列
    orders = SeckillOrder.objects.filter(user_id=user_id).order_by('-create_time')
    
    # 准备订单状态映射
    order_status_map = {
        0: '待支付',
        1: '已支付',
        2: '已取消',
        3: '已完成'
    }
    
    # 计算待支付订单的剩余支付时间（5分钟支付期限）
    current_time = timezone.now()
    orders_with_time_info = []
    for order in orders:
        order_info = {
            'order': order,
            'remaining_time': None  # 剩余支付时间（秒）
        }
        
        # 对于待支付订单，计算剩余支付时间
        if order.status == 0:
            # 订单超时时间为创建时间后5分钟
            timeout_time = order.create_time + timedelta(minutes=5)
            # 计算剩余时间（秒），如果还未超时
            if current_time < timeout_time:
                remaining_seconds = int((timeout_time - current_time).total_seconds())
                order_info['remaining_time'] = remaining_seconds
        
        orders_with_time_info.append(order_info)
    
    return render(request, "orders.html", {
        "orders_with_time_info": orders_with_time_info,
        "order_status_map": order_status_map,
        "user_id": user_id
    })

@sliding_window_limit(threshold=5)
def pay_order(request, order_id):
    """订单支付处理"""
    if request.method == "POST":
        # 获取用户标识
        user_id = request.META.get('HTTP_X_FORWARDED_FOR', '127.0.0.1')

        # 查询订单
        order = SeckillOrder.objects.get(id=order_id, user_id=user_id)

        # 检查订单状态是否为待支付
        if order.status != 0:
            return render(request, "result.html", {
                "code": 400,
                "msg": "订单状态错误，无法支付"
            })
        pay_url = create_url(
            alipay_client,
            subject=order.goods_name,  # 订单标题
            out_trade_no=str(order.id),  # 商户订单号（转换为字符串）
            total_amount=float(order.total_amount)  # 订单金额（转换为浮点数）
        )
        return HttpResponse(f'<script>window.location.href="{pay_url}";</script>')

def pay_result(request):
    try:
        # 获取支付宝返回的所有参数
        params = request.GET.dict()

        # 检查必要参数是否存在
        if not params or 'sign' not in params:
            return render(request, "result.html", {
                "code": 400,
                "msg": "无效的支付结果参数"
            })

        # 提取签名
        sign = params.get('sign')

        # 对通知参数进行处理
        try:
            org_message = get_dic_sorted_params(params)
            # 转换成字节串
            message = bytes(org_message, encoding='utf-8')
        except Exception as e:
            return render(request, "result.html", {
                "code": 400,
                "msg": f"参数处理失败：{str(e)}"
            })

        # 验证签名(同步回调参数不包含trade_status只需验证签名通过，即可认为支付流程完成)
        try:
            verified = verify_with_rsa(
                public_key=settings.ALIPAY_SETTINGS['alipay_public_key'],
                message=message,
                sign=sign,
            )
        except Exception as e:
            return render(request, "result.html", {
                "code": 500,
                "msg": f"签名验证失败：{str(e)}"
            })

        if verified:
            # 验签成功且交易状态有效（仅用于前端展示）
            order_id = params.get("out_trade_no")  # 商户订单号
            return render(request, "result.html", {
                "code": 200,
                "msg": "支付成功",
                "order_id": order_id
            })
        else:
            # 验签失败或交易状态异常
            return render(request, "result.html", {
                "code": 500,
                "msg": "支付结果验证失败"
            })
    except Exception as e:
        # 捕获所有其他未预见的异常
        return render(request, "result.html", {
            "code": 500,
            "msg": f"系统处理支付结果时发生错误：{str(e)}"
        })

@csrf_exempt
def alipay_notify(request):
    if request.method == 'POST':
        # 1. 获取支付宝发送的通知参数（POST形式）
        params = request.POST.dict()
        # 2. 提取签名（用于验证）
        sign = params.get('sign')
        # 3. 对通知参数进行处理
        org_message = get_dic_sorted_params(params)
        # 4. 转换成字节串
        message = bytes(org_message, encoding='utf-8')

        # 5. verify_with_rsa方法验证签名
        verified = verify_with_rsa(
            public_key=settings.ALIPAY_SETTINGS['alipay_public_key'],
            message=message,
            sign=sign,
        )

        # 6. 检查验证状态
        if not verified:
            print("支付宝异步通知：签名验证失败")
            return HttpResponse("fail")  # 签名验证失败返回fail，这是支付宝接口的硬性要求

        trade_status = params.get('trade_status')
        if trade_status not in ['TRADE_SUCCESS', 'TRADE_FINISHED']:
            logging.info(f"支付未成功，状态：{trade_status}")
            return HttpResponse("success")  # 支付宝要求非成功状态也返回success

        # 7. 数据更新逻辑
        try:
            out_trade_no = params.get('out_trade_no')
            order = SeckillOrder.objects.get(id=out_trade_no)

            # 幂等性处理：如果已经支付成功，直接返回
            if order.status == "已支付":
                return HttpResponse("success")

            # 更新订单状态
            order.status = 1

            # 记录支付时间
            order.pay_time = timezone.now()
            # 保存订单信息
            order.save()

            logging.info(f"订单{out_trade_no}支付成功，状态已更新")
        except Exception as e:
            logging.error(f"处理订单失败：{str(e)}")
            return HttpResponse("fail")
        return HttpResponse("success")
    return HttpResponse("fail")  # 非POST请求返回fail


def cancel_order(request, order_id):
    """取消订单"""
    if request.method == "POST":
        try:
            # 获取用户标识
            user_id = request.META.get('HTTP_X_FORWARDED_FOR', '127.0.0.1')
            
            # 查询订单
            order = SeckillOrder.objects.get(id=order_id, user_id=user_id)
            
            # 检查订单状态是否为待支付
            if order.status != 0:
                return render(request, "result.html", {
                    "code": 400,
                    "msg": "订单状态错误，无法取消"
                })
            
            # 更新订单状态为已取消
            order.status = 2
            order.cancel_time = datetime.now()
            order.save()
            
            # 调用任务中的函数恢复库存并解除限购
            restore_stock_and_remove_limit(order.goods_id, user_id)
            
            return render(request, "result.html", {
                "code": 200,
                "msg": "订单已取消，库存已恢复",
                "order_id": order_id
            })
        except SeckillOrder.DoesNotExist:
            return render(request, "result.html", {
                "code": 404,
                "msg": "订单不存在"
            })
        except Exception as e:
            return render(request, "result.html", {
                "code": 500,
                "msg": f"取消失败：{str(e)}"
            })
    
    return render(request, "result.html", {
        "code": 405,
        "msg": "方法不允许"
    })