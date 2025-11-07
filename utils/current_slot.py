def get_current_slot(current_hour):
    time_slots = [8, 10, 12, 14, 16, 18, 20, 22]

    # 1. 0:00-8:00 → 次日8点场
    if 0 <= current_hour < 8:
        return 8

    # 2. 22:00-24:00 → 22点场
    if 22 <= current_hour < 24:
        return 22

    # 3. 8:00-22:00 → 匹配对应的场次（8-10点→8，10-12→10...20-22→20）
    for i in range(7):  # 只遍历前7个场次（8-20点），因为22点已单独处理
        start = time_slots[i]
        end = time_slots[i + 1]
        if start <= current_hour < end:
            return start

    # 理论上不会走到这里，兜底返回8点场
    return 8