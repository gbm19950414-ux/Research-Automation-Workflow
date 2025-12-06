import pandas as pd
import numpy as np
import seaborn as sns
import matplotlib.pyplot as plt

# 设置绘图样式
sns.set(style="whitegrid")

# 读取数据
data = pd.read_csv('pca_data.csv')

# 提取样本编号、组别和脂质成分数据
samples = data.iloc[:, 0]  # 假设第一列是样本编号
groups = data.iloc[:, 1]   # 假设第二列是组别
lipid_data = data.iloc[:, 2:]  # 假设前两列是样本编号和组别

# 标准化数据（Z-score标准化）
lipid_data_standardized = (lipid_data - lipid_data.mean()) / lipid_data.std()

# 创建行标签，合并样本编号和组别信息
row_labels = samples + ' (' + groups + ')'

# 创建热图并进行层次聚类
plt.figure(figsize=(20, 15))
g = sns.clustermap(lipid_data_standardized, method='average', metric='euclidean', cmap='viridis', 
                   standard_scale=1, figsize=(20, 15), 
                   xticklabels=False, yticklabels=row_labels)

# 设置热图标题
plt.title('Heatmap of Lipid Data with Hierarchical Clustering', pad=20)

# 显示热图
plt.show()
