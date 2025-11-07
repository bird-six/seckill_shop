from django.db import models
from django.db.models import Index
from utils.snow_flake import Snowflake


# 秒杀商品模型
class SeckillProduct(models.Model):
    id = models.BigAutoField(primary_key=True, verbose_name="商品唯一标识")
    name = models.CharField(max_length=64, verbose_name="商品名称")
    image = models.CharField(max_length=128, default='/product_img/扫地机器人.webp', verbose_name="商品图片路径")
    base_price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="原价")
    seckill_price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="秒杀价")
    stock = models.IntegerField(verbose_name="秒杀库存")
    seckill_start_time = models.DateTimeField(verbose_name="秒杀开始时间")
    seckill_end_time = models.DateTimeField(verbose_name="秒杀结束时间")
    status = models.SmallIntegerField(choices=(
        (0, '未开始'),
        (1, '进行中'),
        (2, '已结束')
    ), default=0, verbose_name="秒杀状态")
    create_time = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    update_time = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = "seckill_products"
        indexes = [
            Index(fields=['status', 'seckill_start_time', 'seckill_end_time'], name='idx_status_time'),
            Index(fields=['stock'], name='idx_stock')
        ]

# 秒杀订单模型
class SeckillOrder(models.Model):
    id = models.BigIntegerField(primary_key=True, default=Snowflake.generate_id_static, verbose_name="订单唯一标识")
    user_id = models.CharField(max_length=64, verbose_name="用户ID")
    goods_id = models.BigIntegerField(verbose_name="商品ID")
    goods_name = models.CharField(max_length=64, verbose_name="商品名称")
    seckill_price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="秒杀单价")
    quantity = models.SmallIntegerField(verbose_name="购买数量")
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="订单总金额")
    status = models.SmallIntegerField(choices=(
        (0, '待支付'),
        (1, '已支付'),
        (2, '已取消'),
        (3, '已完成')
    ), verbose_name="订单状态")
    create_time = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    pay_time = models.DateTimeField(null=True, blank=True, verbose_name="支付时间")
    cancel_time = models.DateTimeField(null=True, blank=True, verbose_name="取消时间")

    class Meta:
        db_table = "seckill_orders"
        indexes = [
            Index(fields=['user_id', 'create_time'], name='idx_user_create_time'),
            Index(fields=['goods_id', 'status'], name='idx_goods_status'),
            Index(fields=['create_time'], name='idx_create_time')
        ]


