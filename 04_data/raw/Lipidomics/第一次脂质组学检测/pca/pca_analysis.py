import pandas as pd
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler

# 读取数据
data = pd.read_csv('pca_data.csv')  # 使用你的CSV文件名

# 提取特征（假设第一列是样本名称，第二列是组别，其余列是特征）
features = data.iloc[:, 2:]
groups = data['Group']
samples = data['Sample']

# 标准化数据
scaler = StandardScaler()
scaled_features = scaler.fit_transform(features)

# 进行PCA分析
pca = PCA(n_components=2)  # 将数据降到二维
principal_components = pca.fit_transform(scaled_features)

# 获取主成分解释的方差比例
explained_variance = pca.explained_variance_ratio_

# 创建包含PCA结果的DataFrame
pca_df = pd.DataFrame(data=principal_components, columns=['PC1', 'PC2'])
pca_df['Sample'] = samples
pca_df['Group'] = groups

# 保存结果
pca_df.to_csv('pca_results.csv', index=False)

print("PCA分析完成，结果已保存到 'pca_results.csv'")
print(f"PC1解释的方差比例: {explained_variance[0]:.2f}")
print(f"PC2解释的方差比例: {explained_variance[1]:.2f}")
