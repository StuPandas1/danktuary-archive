import pandas as pd
df = pd.read_csv('band_archive.csv')
df['Date'] = pd.to_datetime(df['Date'])
df['Show_Label'] = df['Date'].dt.strftime('%m/%d/%Y') + ' — ' + df['Location']
type_order = {'live': 0, 'trip': 1, 'practice': 2}
df['Type_Order'] = df['Type'].map(type_order).fillna(3)
unique = df.drop_duplicates(subset='Show_Label').sort_values(['Type_Order', 'Date'], ascending=[True, False])
print(unique[['Show_Label', 'Type', 'Type_Order']].head(20))