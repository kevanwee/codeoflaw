import pandas as pd
import matplotlib.pyplot as plt
from collections import Counter

df = pd.read_csv('elitigation_cases_2020_to_2025.csv')

print(f"Total cases: {len(df)}")
print(f"Years covered: {df['Year'].unique()}")
print("\nMissing values:")
print(df.isnull().sum())

# case volume analysis
yearly_counts = df['Year'].value_counts().sort_index()
plt.figure(figsize=(10,5))
yearly_counts.plot(kind='bar', color='skyblue')
plt.title('Case Volume by Year')
plt.xlabel('Year')
plt.ylabel('Number of Cases')
plt.show()

# judge analysis
authors = df['Author'].str.split(', ', expand=True).stack().value_counts()
top_authors = authors.head(10)
plt.figure(figsize=(12,6))
top_authors.plot(kind='barh', color='lightgreen')
plt.title('Top 10 Most Active Authors')
plt.xlabel('Number of Cases')
plt.show()

# legal area analysis (from catchwords)
legal_terms = []
for terms in df['Catchwords'].dropna():
    legal_terms.extend([t.strip() for t in terms.split('—') if t.strip()])
term_counts = Counter(legal_terms).most_common(15)

terms, counts = zip(*term_counts)
plt.figure(figsize=(12,8))
plt.barh(terms, counts, color='salmon')
plt.title('Top 15 Legal Terms in Catchwords')
plt.xlabel('Frequency')
plt.gca().invert_yaxis()
plt.show()

# document complexity analysis
print("\nDocument Complexity Statistics:")
print(f"Average word count: {df['WordCount'].mean():.0f}")
print(f"Median word count: {df['WordCount'].median():.0f}")
print(f"Longest document: {df['WordCount'].max():,} words")
print(f"Average paragraphs: {df['ParagraphCount'].mean():.0f}")

plt.figure(figsize=(10,6))
plt.scatter(df['WordCount'], df['ParagraphCount'], alpha=0.6)
plt.title('Word Count vs Paragraph Count')
plt.xlabel('Word Count')
plt.ylabel('Paragraph Count')
plt.show()
