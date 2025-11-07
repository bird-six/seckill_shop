"""
批量创建秒杀商品记录脚本
"""
import os
import sys
from datetime import datetime, timedelta

# 1. 设置项目根目录到系统路径
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

# 2. 设置Django环境变量
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'seckill_shop.settings')

# 3. 导入Django和模型
import django
django.setup()

# 现在可以导入Django模型了
from shop.models import SeckillProduct


def create_products():
    """
    创建24条商品记录：
    - 名称为测试商品1~24
    - 原始价格399
    - 秒杀价309
    - 库存5~50随机
    - 秒杀开始时间的年月日为当前年月日，时间是8:00、10：00、12：00，14：00，16：00，18：00、20：00、22：00八个时间
    - 结束时间为开始时间往后推迟两小时
    """
    # 准备秒杀开始时间列表
    today = datetime.now().date()
    # 创建带有时区信息的日期时间对象
    from django.utils import timezone
    start_date = timezone.make_aware(datetime(today.year, today.month, today.day))
    time_points = [
        start_date.replace(hour=8, minute=0, second=0, microsecond=0),
        start_date.replace(hour=10, minute=0, second=0, microsecond=0),
        start_date.replace(hour=12, minute=0, second=0, microsecond=0),
        start_date.replace(hour=14, minute=0, second=0, microsecond=0),
        start_date.replace(hour=16, minute=0, second=0, microsecond=0),
        start_date.replace(hour=18, minute=0, second=0, microsecond=0),
        start_date.replace(hour=20, minute=0, second=0, microsecond=0),
        start_date.replace(hour=22, minute=0, second=0, microsecond=0)
    ]

    # 创建24条商品记录
    products = []
    for i in range(1, 25):
        # 确定当前商品的开始时间点，使用模运算确保均匀分配
        time_index = (i - 1) % 8
        start_time = time_points[time_index]
        # 秒杀结束时间设置为开始时间后2小时
        end_time = start_time + timedelta(hours=2)

        # 创建商品对象
        product = SeckillProduct(
            name=f"测试商品{i}",
            base_price=399.00,
            seckill_price=309.00,
            # stock=random.randint(5, 50),  # 随机库存5~50
            stock=50,  # 库存
            seckill_start_time=start_time,
            seckill_end_time=end_time,
            status=0  # 未开始
        )
        products.append(product)

    # 批量插入数据库
    SeckillProduct.objects.bulk_create(products)
    print(f"成功创建了{len(products)}条商品记录")

if __name__ == '__main__':
    create_products()
