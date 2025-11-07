from functools import wraps
import time
import django_redis
from django.http import HttpResponse

redis_client = django_redis.get_redis_connection("default")


def sliding_window_limit(threshold):
    """
    滑动窗口限流装饰器
    将1秒拆分为10个100ms小窗口，使用ZSet记录请求时间戳
    :param threshold: 1秒内最大允许的请求数
    """

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            # 生成限流键
            user_identifier = request.META.get('REMOTE_ADDR')  # 使用IP地址作为标识
            key = f"limit:{user_identifier}:{request.path}"

            # 当前时间戳（毫秒）
            current_ts = int(time.time() * 1000)
            # 窗口起始时间（当前时间前1秒）
            window_start_ts = current_ts - 1000

            try:
                # 使用Redis管道确保操作原子性
                with redis_client.pipeline() as pipe:
                    # 添加当前请求时间戳到ZSet
                    pipe.zadd(key, {current_ts: current_ts})
                    # 移除窗口之外的记录（1秒前的）
                    pipe.zremrangebyscore(key, 0, window_start_ts)
                    # 设置键过期时间，避免内存泄漏
                    pipe.expire(key, 3)  # 过期时间设为3秒足够覆盖窗口
                    # 统计当前窗口内的请求数
                    pipe.zcard(key)

                    # 执行所有命令
                    results = pipe.execute()
                    current_count = results[-1]  # 获取zcard的结果

                # 检查是否超过阈值
                if current_count > threshold:
                    return HttpResponse("请求过于频繁，3秒后再试", status=429)

            except Exception as e:
                # Redis操作失败时的容错处理，这里简单返回服务器错误
                return HttpResponse(f"系统繁忙，请稍后再试:{e}", status=500)

            # 正常执行视图函数
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator
