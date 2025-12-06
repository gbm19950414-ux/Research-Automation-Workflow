import os, re, pandas as pd, openai, tiktoken, textwrap, time

OPENAI_API_KEY = "sk-................................................"
openai.api_key = OPENAI_API_KEY

SRC = "IL1B_疾病模型_中文加类别.csv"
DST = "IL1B_中文全译.csv"
BATCH = 40          # 每批最多翻译 40 行，防止上下文过长
MODEL = "gpt-4o-mini"  # 成本与速度兼顾；改成 "gpt-4o" 可进一步提升质量

df = pd.read_csv(SRC)

def zh_time(text):
    if pd.isna(text): return ""
    return (text.replace(" h", " 小时")
                .replace(" d", " 天")
                .replace(" min", " 分钟")
                .replace(" m", " 分钟"))

# 分批翻译长段英文文本
def translate_batch(texts):
    prompt = ("请将下面的内容逐行翻译成中文，保持科技论文语气，"
              "专有名词用规范中文或英文缩写，行间顺序不能变：\n\n")
    whole = prompt + "\n".join(texts)
    rsp = openai.ChatCompletion.create(
        model=MODEL,
        messages=[{"role": "user", "content": whole}],
        temperature=0.2,
    )
    return [line.strip() for line in rsp.choices[0].message.content.split("\n")]

for col in ["疾病/病理状态", "诱导/刺激方式", "因果验证实验（回补）"]:
    translated = []
    block = []
    for i, txt in enumerate(df[col].fillna("")):
        block.append(txt)
        # 到批量大小或最后一行就翻译一次
        if len(block) == BATCH or i == len(df)-1:
            translated += translate_batch(block)
            block = []
            time.sleep(1.2)   # 避免打 API 过快
    df[col] = translated

# 时间列直接规则替换
df["IL-1β下降所需时间"] = df["IL-1β下降所需时间"].apply(zh_time)

df.to_csv(DST, index=False)
print(f"✔ 已保存：{DST}")
