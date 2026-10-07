import gspread
import gspread_dataframe as gd
import pandas as pd
from google.oauth2.service_account import Credentials

class GoogleClient:
    def __init__(self, config):
        self.config = config
        credentials = Credentials.from_service_account_file(config['credentials_path'], scopes=config['scope'])
        self.google_connect = gspread.authorize(credentials)
        self.worksheet = None

    def get_data(self):
        print("Скачиваем гугл таблицу:", self.config['google_sheet_url'])
        table = self.google_connect.open_by_url(self.config['google_sheet_url'])
        self.worksheet = table.get_worksheet_by_id(self.config['worksheet_id'])
        df = pd.DataFrame(self.worksheet.get_all_records())
        df = df.replace('', None)
        return df

    def send_data(self, to_google_df):
        print("Обновляем гугл таблицу")
        gd.set_with_dataframe(self.worksheet, to_google_df)
