import pandas as pd
import numpy as np
from scipy.stats import ttest_ind
import matplotlib.pyplot as plt

# 加载数据
file_path = '/Users/gongbaoming/Library/CloudStorage/OneDrive-个人/发育生物所/博士课题/EPHB1/文件/数据处理/数据汇总/脂质组学分析/another/pca_data.csv'
data = pd.read_csv(file_path)

# 移除包含脂质类型和子分类的第一行
data.columns = data.iloc[0]
data = data.drop(0)

# 重置索引，确保DataFrame格式正确
data = data.reset_index(drop=True)

# 将所有脂质数据转换为数值类型，遇到错误强制转换为NaN
data.iloc[:, 2:] = data.iloc[:, 2:].apply(pd.to_numeric, errors='coerce')

# 按WT和KO组分组数据
wt_data = data[data['Group'] == 'WT']
ko_data = data[data['Group'] == 'KO']

# 对每种脂质类型进行t检验并存储结果
results = []
for lipid in data.columns[2:]:
    wt_values = wt_data[lipid].dropna().astype(float)
    ko_values = ko_data[lipid].dropna().astype(float)
    if len(wt_values) > 1 and len(ko_values) > 1:  # 确保有足够的数据点
        t_stat, p_value = ttest_ind(wt_values, ko_values, equal_var=False)
        results.append((lipid, t_stat, p_value))

# 创建DataFrame存储结果
results_df = pd.DataFrame(results, columns=['Lipid', 'T-Statistic', 'P-Value'])

# 计算每种脂质的Fold Change（KO组均值/WT组均值）
results_df['WT_Mean'] = [wt_data[lipid].mean() for lipid in results_df['Lipid']]
results_df['KO_Mean'] = [ko_data[lipid].mean() for lipid in results_df['Lipid']]
results_df['Fold_Change'] = np.log2(results_df['KO_Mean'] / results_df['WT_Mean'])

# 创建-log10(p-value)列
results_df['-Log10(P-Value)'] = -np.log10(results_df['P-Value'])

# 绘制火山图
plt.figure(figsize=(10, 6))
plt.scatter(results_df['Fold_Change'], results_df['-Log10(P-Value)'], color='gray')

# 突出显示p值<0.05的点
significant = results_df['P-Value'] < 0.05
plt.scatter(results_df['Fold_Change'][significant], results_df['-Log10(P-Value)'][significant], color='red')

plt.title('Volcano Plot')
plt.xlabel('Log2(Fold Change)')
plt.ylabel('-Log10(P-Value)')
plt.axhline(y=-np.log10(0.05), color='blue', linestyle='--')
plt.axvline(x=1, color='green', linestyle='--')
plt.axvline(x=-1, color='green', linestyle='--')

plt.show()

# 按P-Value排序并展示结果
results_df = results_df.sort_values(by='P-Value')
print(results_df.head())
