from alipay.aop.api.AlipayClientConfig import AlipayClientConfig
from alipay.aop.api.DefaultAlipayClient import DefaultAlipayClient
from alipay.aop.api.domain.AlipayTradePagePayModel import AlipayTradePagePayModel
from alipay.aop.api.request.AlipayTradePagePayRequest import AlipayTradePagePayRequest

from seckill_shop import settings

def create_alipay_client():
    # 初始化客户端配置对象AlipayClientConfig
    alipay_client_config = AlipayClientConfig()     # 初始化支付宝客户端配置对象
    alipay_client_config.server_url = 'https://openapi-sandbox.dl.alipaydev.com/gateway.do'     # 沙箱环境  正式环境为：'https://openapi.alipay.com/gateway.do'
    alipay_client_config.app_id = settings.ALIPAY_SETTINGS['appid']    # 应用ID
    alipay_client_config.app_private_key = settings.ALIPAY_SETTINGS['app_private_key']    # 应用私钥
    alipay_client_config.alipay_public_key = settings.ALIPAY_SETTINGS['alipay_public_key']    # 支付宝公钥
    alipay_client_config.sign_type = settings.ALIPAY_SETTINGS['sign_type']  # 签名类型（默认RSA2）
    alipay_client = DefaultAlipayClient(alipay_client_config)
    return alipay_client

def create_url(alipay_client, subject, out_trade_no, total_amount):
    # 构建请求参数
    page_pay_model = AlipayTradePagePayModel()
    page_pay_model.out_trade_no = out_trade_no  # 商户订单号（唯一）
    page_pay_model.total_amount = "{0:.2f}".format(total_amount)  # 订单金额
    page_pay_model.subject = subject  # 订单标题
    page_pay_model.product_code = "FAST_INSTANT_TRADE_PAY"
    # 创建支付请求对象
    page_pay_request = AlipayTradePagePayRequest(biz_model=page_pay_model)  # 关联订单参数模型
    page_pay_request.return_url = settings.ALIPAY_SETTINGS["app_return_url"]  # 同步回调地址（用户支付后跳转）
    page_pay_request.notify_url = settings.ALIPAY_SETTINGS["app_notify_url"]  # 异步通知地址（核心状态通知）

    # 生成支付链接
    pay_url = alipay_client.page_execute(page_pay_request, http_method='GET')

    return pay_url

# 通知参数处理函数
def get_dic_sorted_params(org_dic_params):
    content = ''
    org_dic_params.pop('sign')
    org_dic_params.pop('sign_type')  # 去除sign、sigh_type
    new_list = sorted(org_dic_params, reverse=False)  # 待验签参数进行排序
    for i in new_list:
        p = i + '=' + org_dic_params.get(i) + '&'
        content += p
    sorted_params = content.strip('&')  # 重组字符串，将{k:v}形式的字典类型原始响应值--》转换成'k1=v1&k2=v2'形式的字符串格式
    return sorted_params