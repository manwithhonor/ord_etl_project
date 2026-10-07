import pandas as pd
from datetime import datetime

class TransformHandler:
    def __init__(self, config):
        self.platform_dict = config['yandex']['platform_dict']
        self.report_date = config['app']['report_date']

    def _calculate_date_start(self, pub_date):
        pub = pd.to_datetime(pub_date)
        now = pd.to_datetime(self.report_date) # datetime.now()
        current_month_start = datetime(now.year, now.month, 1)
        date_start = pub if (pub.year == now.year and pub.month == now.month) else current_month_start
        return date_start.strftime('%Y-%m-%d')

    def _process_columns_for_yandex(self, df: pd.DataFrame) -> pd.DataFrame:
        df['creativeId'] = df["creativeId"].str.replace("c-FV0R-", "")
        df['impsPlan'] = df['impsFact']
        df['amountPerUnit'] = "0.00000"
        df['type'] = "other"
        df['platformId'] = df["platform"].apply(lambda x: self.platform_dict[x])
        df.drop("platform", axis=1, inplace=True)
        return df

    def _process_dt_columns_for_yandex(self, df: pd.DataFrame) -> pd.DataFrame:
        df['dateStartFact'] = df['dateStartFact'].apply(self._calculate_date_start)
        df['dateStartPlan'] = df['dateStartFact']
        df['dateEndFact'] = self.report_date
        df['dateEndPlan'] = self.report_date

        datetime_cols = ['dateStartFact', 'dateStartPlan', 'dateEndFact', 'dateEndPlan']
        for col in datetime_cols:
            df[col] = pd.to_datetime(df[col])  # 1. Конвертируем в datetime
            df[col] = df[col].dt.strftime('%Y-%m-%d')  # 2. Конвертируем обратно в строку в нужном формате
        return df

    @staticmethod
    def _make_payload_for_yandex(df: pd.DataFrame) -> dict:
        records = df.to_dict('records')
        for row in records:
            row['amount'] = {
                "excludingVat": "0",
                "includingVat": "0",
                "vat": "0",
                "vatRate": "0",
            }
        payload = {"statistics": records}
        return payload

    @staticmethod
    def _make_simple_views(row):
        delta_flag = row['delta_flag']
        if delta_flag:
            delta = row['current_views'] - row['imps_total']
        else:
            delta = 0
        return delta

    @staticmethod
    def _prepare_merged_df(livedune_df, google_df):
        merged_df = google_df.merge(livedune_df, how='left', on=['platform', 'platform_url'])  # , suffixes=('_livedune', '_bd')
        assert merged_df['current_views'].isna().sum() == 0, "join failed"
        merged_df['current_views'] = merged_df['current_views'].fillna(0)
        merged_df['current_views'] = merged_df['current_views'].astype('int')
        merged_df['imps_total'] = merged_df['imps_total'].fillna(0)
        merged_df['imps_total'] = merged_df['imps_total'].astype('int')
        merged_df['delta_flag'] = merged_df['current_views'] >= merged_df['imps_total']
        merged_df['dup_flag'] = merged_df.duplicated(['platform', 'creativeId'], keep=False)
        return merged_df

    @staticmethod
    def _split_by_dups(merged_df):
        not_dup_df = merged_df.query('dup_flag == False')
        dup_df = merged_df.query('dup_flag == True')
        return not_dup_df, dup_df

    def _prepare_not_dupped_df(self, not_dup_df):
        not_dup_df['month_delta'] = not_dup_df.apply(self._make_simple_views, axis=1)
        to_yandex_1 = not_dup_df[['platform', 'creativeId', 'created_dt', 'month_delta']]
        return not_dup_df, to_yandex_1

    @staticmethod
    def _prepare_dupped_df(dup_df):
        # если повтоярется плафторма и айди кретива, но отличается ссылка на пост, то просмотры за такие посты суммируем
        to_yandex_2 = dup_df.groupby(['platform', 'creativeId']).agg(created_dt=('created_dt', 'min'),
                                                                     old_views=('imps_total', 'sum'),
                                                                     current_views=('current_views', 'sum')).reset_index()
        to_yandex_2['month_delta'] = to_yandex_2['current_views'] - to_yandex_2['old_views']
        to_yandex_2 = to_yandex_2.drop(['current_views', 'old_views'], axis=1)
        dup_df = dup_df.merge(to_yandex_2[['platform', 'creativeId', 'month_delta']], how='left', on=['platform', 'creativeId'])
        return dup_df, to_yandex_2

    def _make_month_delta_name(self):
        lst = self.report_date.split("-")
        return f"imps_{lst[1]}_{lst[0][2:]}"

    def _prepare_to_google_df(self, not_dup_df, dup_df) -> pd.DataFrame:
        to_google_df = pd.concat([not_dup_df, dup_df])
        to_google_df = to_google_df.sort_values(by=['creativeId', 'platform', 'created_dt'])
        to_google_df['imps_total'] = to_google_df['current_views']
        to_google_df = to_google_df.drop(['current_views', 'delta_flag', 'dup_flag'], axis=1)
        to_google_df = to_google_df.reset_index(drop=True)
        to_google_df = to_google_df.rename(columns={'month_delta': self._make_month_delta_name()})

        cols = to_google_df.columns.tolist()
        cols[-2], cols[-1] = cols[-1], cols[-2]  # Меняем последние две местами
        to_google_df = to_google_df[cols]
        return to_google_df

    @staticmethod
    def _prepare_to_yandex_df(to_yandex_1, to_yandex_2) -> pd.DataFrame:
        to_yandex_df = pd.concat([to_yandex_1, to_yandex_2])
        to_yandex_df.columns = ['platform', 'creativeId', 'dateStartFact', 'impsFact']
        return to_yandex_df

    def transform_exracted_data(self, livedune_df, google_df):
        merged_df = self._prepare_merged_df(livedune_df, google_df)
        not_dup_df, dup_df = self._split_by_dups(merged_df)

        not_dup_df, to_yandex_1 = self._prepare_not_dupped_df(not_dup_df)
        dup_df, to_yandex_2 = self._prepare_dupped_df(dup_df)

        to_google_df = self._prepare_to_google_df(not_dup_df, dup_df)
        to_yandex_df = self._prepare_to_yandex_df(to_yandex_1, to_yandex_2)
        return to_google_df, to_yandex_df

    def transform_to_yandex_data(self, df) -> dict:
        print("Преобразуем данные")
        df = self._process_columns_for_yandex(df)
        df = self._process_dt_columns_for_yandex(df)
        payload = self._make_payload_for_yandex(df)
        return payload
