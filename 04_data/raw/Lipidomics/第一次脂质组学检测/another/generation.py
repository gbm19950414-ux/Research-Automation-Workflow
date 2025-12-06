import pandas as pd
import numpy as np
from scipy.stats import ttest_ind
import seaborn as sns
import matplotlib.pyplot as plt

# 读取数据
data_path = '/Users/gongbaoming/Library/CloudStorage/OneDrive-个人/发育生物所/博士课题/EPHB1/文件/数据处理/数据汇总/脂质组学分析/another/pca_data.csv'
data = pd.read_csv(data_path, header=1)

# 检查数据格式和列名
print(data.head())
print(data.columns)

# 提取样本编号和组别
samples = data.iloc[:, 0]  # 第一列是样本编号
groups = data.iloc[:, 1]   # 第二列是分组

# 提取脂质类型和子分类信息
lipid_types = data.columns[2:]  # 从第三列开始是脂质类型
sub_categories = data.iloc[0, 2:]  # 第二行是子分类信息

# 重塑数据框
data_long = pd.melt(data.iloc[1:, :], id_vars=['Sample', 'Group'], var_name='Lipid', value_name='Value')

# 修正LipidType和SubCategory列
data_long['LipidType'] = data_long['Lipid'].apply(lambda x: x.split('.')[0])
data_long['SubCategory'] = data_long['Lipid'].apply(lambda x: x.split('.')[1] if '.' in x else x)

# 计算每个脂质子分类在WT和KO组中的均值和标准差
summary = data_long.groupby(['LipidType', 'SubCategory', 'Group']).agg(
    Mean=('Value', 'mean'),
    Std=('Value', 'std')
).reset_index()

# 进行显著性检验并计算Fold Change
results = []

lipid_types = data_long['LipidType'].unique()
subcategories = data_long['SubCategory'].unique()

for lipid_type in lipid_types:
    for subcategory in subcategories:
        wt_values = data_long[(data_long['LipidType'] == lipid_type) & (data_long['SubCategory'] == subcategory) & (data_long['Group'] == 'WT')]['Value']
        ko_values = data_long[(data_long['LipidType'] == lipid_type) & (data_long['SubCategory'] == subcategory) & (data_long['Group'] == 'KO')]['Value']
        
        if len(wt_values) > 1 and len(ko_values) > 1:
            t_stat, p_value = ttest_ind(wt_values, ko_values, equal_var=False)
            fold_change = np.mean(ko_values) / np.mean(wt_values)
            results.append({
                'LipidType': lipid_type,
                'SubCategory': subcategory,
                'PValue': p_value,
                'FoldChange': fold_change
            })

results_df = pd.DataFrame(results)
results_df['-log10(PValue)'] = -np.log10(results_df['PValue'])

# 生成火山图
plt.figure(figsize=(10, 8))
sns.scatterplot(data=results_df, x='FoldChange', y='-log10(PValue)', hue='LipidType')
plt.axhline(y=-np.log10(0.05), color='red', linestyle='--')
plt.title('Volcano Plot of Lipid Types')
plt.xlabel('Fold Change')
plt.ylabel('-log10(PValue)')
plt.legend(title='Lipid Type')
plt.show()

# 排序结果
sorted_results = results_df.sort_values(by='PValue')

# 取前10个差异最大的脂质类型及其子分类
top_results = sorted_results.head(10)

# 生成条形图
plt.figure(figsize=(12, 6))
sns.barplot(data=top_results, x='FoldChange', y='SubCategory', hue='LipidType', dodge=False)
plt.axvline(x=1, color='grey', linestyle='--')
plt.title('Top 10 Lipid Subcategories with Largest Differences')
plt.xlabel('Fold Change')
plt.ylabel('SubCategory')
plt.legend(title='Lipid Type')
plt.show()
