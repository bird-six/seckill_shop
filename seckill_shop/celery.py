import os
from celery import Celery

# 设置Django环境变量
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'seckill_shop.settings')

# 创建Celery应用实例
app = Celery('seckill_shop')

# 从Django设置中加载配置，使用命名空间'CELERY'来避免冲突
app.config_from_object('django.conf:settings', namespace='CELERY')

# 自动发现并注册所有已安装应用中的任务
app.autodiscover_tasks()

# 配置定时任务调度器
app.conf.beat_schedule = {
    # 检查并更新秒杀商品状态
    'check-and-update-product-status-10-seconds': {
        'task': 'shop.tasks.update_seckill_status',
        'schedule': 10.0,  # 每10秒执行一次
    },
    # 预热秒杀商品
    'preheat_seckill_products-every-minute': {
        'task': 'shop.tasks.preheat_seckill_products',
        'schedule': 60.0,  # 每60秒执行一次
    },
}

# 设置时区
app.conf.timezone = 'Asia/Shanghai'