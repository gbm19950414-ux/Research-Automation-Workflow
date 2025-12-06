import pandas as pd
import numpy as np
import seaborn as sns
import matplotlib.pyplot as plt

# 读取数据
data = pd.read_csv('pca_data.csv')

# 提取脂质成分数据
lipid_data = data.iloc[:, 2:]  # 假设前两列是样本名和组别

# 标准化数据（Z-score标准化）
lipid_data_standardized = (lipid_data - lipid_data.mean()) / lipid_data.std()

# 将标准化后的数据和组别、样本名合并
data_standardized = pd.concat([data.iloc[:, :2], lipid_data_standardized], axis=1)
