import math
import django_redis
import mmh3


class BloomFilter:
    """布隆过滤器实现，用于过滤不存在的商品ID"""

    def __init__(self, key, capacity=100000, error_rate=0.001):
        self.key = key
        self.capacity = capacity  # 预计元素数量
        self.error_rate = error_rate  # 可接受的误判率
        self.redis_client = django_redis.get_redis_connection("default")

        # 计算所需的位数和哈希函数数量
        self.bit_size = int(-(self.capacity * math.log(self.error_rate)) / (math.log(2) ** 2)) + 1
        self.hash_count = int((self.bit_size / self.capacity) * math.log(2)) + 1

    def add(self, item):
        """添加元素到布隆过滤器"""
        for seed in range(self.hash_count):
            hash_value = mmh3.hash(str(item), seed) % self.bit_size
            self.redis_client.setbit(self.key, hash_value, 1)

    def contains(self, item):
        """判断元素是否可能存在于集合中"""
        for seed in range(self.hash_count):
            hash_value = mmh3.hash(str(item), seed) % self.bit_size
            if not self.redis_client.getbit(self.key, hash_value):
                return False
        return True

    def batch_add(self, items):
        """批量添加元素"""
        pipeline = self.redis_client.pipeline()
        for item in items:
            for seed in range(self.hash_count):
                hash_value = mmh3.hash(str(item), seed) % self.bit_size
                pipeline.setbit(self.key, hash_value, 1)
        pipeline.execute()