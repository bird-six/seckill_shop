# Lua脚本：原子检查并扣减库存 (返回1=成功, 0=库存不足)
STOCK_DECR_SCRIPT = """
local stock_key = KEYS[1]
local product_key = KEYS[2]
local user_limit_key = KEYS[3]
local user_id = ARGV[1]

-- 检查用户是否已购买
if redis.call('sismember', user_limit_key, user_id) == 1 then
    return 2  -- 2表示用户已购买
end

-- 检查库存
local stock = redis.call('get', stock_key)
if not stock or tonumber(stock) <= 0 then
    return 0  -- 0表示库存不足
end

-- 扣减库存
redis.call('decr', stock_key)
-- 记录用户购买记录
redis.call('sadd', user_limit_key, user_id)
-- 更新商品缓存中的库存
redis.call('hset', product_key, 'stock', tonumber(stock) - 1)
return 1  -- 1表示扣减成功
"""
