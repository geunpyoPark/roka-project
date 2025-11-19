def calc_cps(text: str, duration_sec: float):
    char_count = len(text.replace(" ", ""))
    if duration_sec == 0:
        return 0.0, char_count
    cps = char_count / duration_sec
    return cps, char_count

def speed_label(cps: float):
    if cps < 3:
        return "매우 느림"
    elif cps < 4:
        return "약간 느림"
    elif cps < 4.8:
        return "보통"
    elif cps < 5.6:
        return "약간 빠름"
    else:
        return "매우 빠름"
