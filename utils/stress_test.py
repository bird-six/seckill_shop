import requests
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading


def generate_random_ip():
    """生成随机IP地址"""
    return f"{random.randint(1, 255)}.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}"


def create_ip_pool(count=100):
    """创建指定数量的随机IP池"""
    return [generate_random_ip() for _ in range(count)]


def generate_random_id():
    """生成244到267之间的随机id"""
    return random.randint(268, 315)


def send_request(base_url, ip, data=None):
    """发送POST请求（包含随机id的接口地址）"""
    # 生成随机id并拼接完整URL
    target_id = generate_random_id()
    url = f"{base_url}/{target_id}/"

    headers = {
        'X-Forwarded-For': ip,
        'Content-Type': 'application/json',  # 根据接口实际需求调整
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    try:

        start_time = time.time()
        response = requests.post(url, headers=headers, json=data, timeout=10)
        end_time = time.time()

        return {
            'status': 'success',
            'ip': ip,
            'id': target_id,  # 记录当前请求的id
            'status_code': response.status_code,
            'response_time': end_time - start_time,
            'thread_id': threading.current_thread().ident
        }
    except Exception as e:
        end_time = time.time()
        return {
            'status': 'error',
            'ip': ip,
            'id': target_id,  # 记录当前请求的id
            'error': str(e),
            'response_time': end_time - start_time,
            'thread_id': threading.current_thread().ident
        }


def run_concurrent_tests(base_url, ip_pool, total_requests=1000, max_workers=50, data=None):
    """运行并发测试"""
    print(f"开始并发测试 - 总请求数: {total_requests}, 最大并发数: {max_workers}")
    print(f"接口地址格式: {base_url}/id")
    start_time = time.time()

    success_count = 0
    failure_count = 0
    total_response_time = 0
    id_request_count = {}  # 统计每个id的请求次数

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 提交所有任务
        futures = [
            executor.submit(send_request, base_url, random.choice(ip_pool), data)
            for _ in range(total_requests)
        ]

        # 处理结果
        for future in as_completed(futures):
            result = future.result()
            total_response_time += result['response_time']

            # 统计每个id的请求次数
            target_id = result['id']
            id_request_count[target_id] = id_request_count.get(target_id, 0) + 1

            if result['status'] == 'success':
                success_count += 1
                if success_count % 100 == 0:  # 每100个成功请求打印一次进度
                    print(f"已完成 {success_count} 个请求...")
            else:
                failure_count += 1
                # 打印错误信息（包含id方便排查）
                print(f"请求失败 - IP: {result['ip']}, ID: {result['id']}, 错误: {result['error']}")

    end_time = time.time()
    total_time = end_time - start_time

    # 打印统计信息
    print("\n测试完成!")
    print(f"总耗时: {total_time:.2f} 秒")
    print(f"总请求数: {total_requests}")
    print(f"成功请求数: {success_count} ({success_count / total_requests * 100:.2f}%)")
    print(f"失败请求数: {failure_count} ({failure_count / total_requests * 100:.2f}%)")
    print(f"平均响应时间: {total_response_time / success_count:.4f} 秒" if success_count > 0 else "无成功请求")
    print(f"每秒请求数: {total_requests / total_time:.2f}")

    # 打印id请求分布（前10个，方便查看分布均匀性）
    print("\n部分ID请求次数分布（共24个ID）:")
    sorted_ids = sorted(id_request_count.items(), key=lambda x: x[0])
    for idx, (id_val, count) in enumerate(sorted_ids[:10]):
        print(f"ID {id_val}: {count}次", end=" | " if (idx + 1) % 5 != 0 else "\n")
    if len(sorted_ids) > 10:
        print(f"... 剩余{len(sorted_ids) - 10}个ID")


if __name__ == "__main__":
    # 配置参数
    BASE_API_URL = "http://localhost:8000/buy"  # 基础URL，后续会拼接/id
    IP_COUNT = 100  # 生成100个随机IP
    TOTAL_REQUESTS = 3000  # 总请求数（可调整）
    MAX_WORKERS = 100  # 最大并发数（可调整）

    # 根据接口需求设置POST数据（如不需要可留空）
    POST_DATA = {
        # "参数1": "值1",
        # "参数2": "值2"
    }

    # 创建IP池
    ip_pool = create_ip_pool(IP_COUNT)
    print(f"已生成 {IP_COUNT} 个随机IP地址")

    # 运行并发测试
    run_concurrent_tests(BASE_API_URL, ip_pool, TOTAL_REQUESTS, MAX_WORKERS, POST_DATA)