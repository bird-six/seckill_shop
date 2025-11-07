from django.contrib import admin
from .models import SeckillProduct, SeckillOrder

@admin.register(SeckillProduct)
class SeckillProductAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'base_price', 'seckill_price', 'stock', 'status', 'seckill_start_time', 'seckill_end_time')
    list_filter = ('status',)
    search_fields = ('name',)

@admin.register(SeckillOrder)
class SeckillOrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'user_id', 'goods_id', 'goods_name', 'seckill_price', 'quantity', 'total_amount', 'status', 'create_time')
    list_filter = ('status',)
    search_fields = ('user_id', 'goods_id', 'goods_name')
