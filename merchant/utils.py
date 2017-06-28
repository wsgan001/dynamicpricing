import sys
import logging

sys.path.append('./')
sys.path.append('../')
from merchant_sdk.api import KafkaApi, PricewarsRequester
import os
import base64
import hashlib
import sys
import numpy as np
import datetime
import csv
from collections import defaultdict
import requests
import bisect


INITIAL_BUYOFFER_CSV_PATH = '../data/buyOffer.csv'
INITIAL_MARKETSITUATION_CSV_PATH = '../data/marketSituation.csv'


class TrainingData():
    """
    self.market_situations =
    {
        product_id: {
            timestamp: {
                merchant_id: {
                    offer_id: [ price, quality, ...]
                }
            }
        }
    }

    self.sales =
    {
        product_id: {
            timestamp: {
                offer_id: [ price, quality, ... ]
            }

        }
    } """
    def __init__(self, merchant_token, market_situations_json=None,
                 sales_json=None):
        self.market_situations = dict()
        self.sales = dict()
        self.merchant_token = merchant_token

    def create_training_data(self, product_id, interval_length=5):

        return [], [[]]

    def print_info(self):
        timestamps_ms = []
        counter_ms = 0
        for product in self.market_situations.values():
            for timestamp, merchant in product.items():
                bisect.insort(timestamps_ms, timestamp)
                for offer in merchant.values():
                    counter_ms += len(offer.keys())
        timestamps_s = []
        counter_s = 0
        for product in self.sales.values():
            for timestamp, offer in product.items():
                bisect.insort(timestamps_s, timestamp)
                counter_s += len(offer.keys())

        print("\nTraining data: \n\tEntries market_situations: {} \
               \n\tEntries sales: {} \
               \n\nmarket_situations: \
               \n\tDistinct timestamps: {} \
               \n\tFirst timestamp: {} \
               \n\tLast timestamp: {} \
               \n\nsales: \
               \n\tFirst timestamp: {} \
               \n\tLast timestamp: {} \n\
               ".format(counter_ms, counter_s, len(timestamps_ms),
                        timestamps_ms[0], timestamps_ms[-1], timestamps_s[0],
                        timestamps_s[-1]))

    def store_as_json(self):
        pass

    def append_marketplace_situations(self, line):
        """ Return 1 if offer already exists in self.market_situations. """
        dict_keys = [line["product_id"], line["timestamp"], line["merchant_id"]]
        ms = self.market_situations
        for dk in dict_keys:
            if dk not in ms:
                ms[dk] = dict()
            ms = ms[dk]
        if line["offer_id"] in ms:
            return 1
        else:
            # TODO Add shipping_time, prime, etc.
            ms[line["offer_id"]] = [line["price"], line["quality"]]
            return 0

    def append_sales(self, line):
        """ Return 1 if offer already exists in self.sales. """
        dict_keys = [line["product_id"], line["timestamp"]]
        s = self.sales
        for dk in dict_keys:
            if dk not in s:
                s[dk] = dict()
            s = s[dk]
        if line["offer_id"] in s:
            return 1
        else:
            s[line["offer_id"]] = [line["price"], line["quality"]]
            return 0

    def append_by_csvs(self, market_situations_path, buy_offer_path):
        with open(market_situations_path, 'r') as csvfile:
            situation_data = csv.DictReader(csvfile)
            for line in situation_data:
                self.append_marketplace_situations(line)

        with open(buy_offer_path, 'r') as csvfile:
            buy_offer_data = csv.DictReader(csvfile)
            for line in buy_offer_data:
                self.append_sales(line)

    def download_kafka_files(self):
        logging.debug('Downloading files from Kafka ...')
        PricewarsRequester.add_api_token(self.merchant_token)
        kafka_url = os.getenv('PRICEWARS_KAFKA_REVERSE_PROXY_URL', 'http://127.0.0.1:8001')
        kafka_api = KafkaApi(host=kafka_url)
        data_url_ms = kafka_api.request_csv_export_for_topic('marketSituation')
        data_url_bo = kafka_api.request_csv_export_for_topic('buyOffer')
        return requests.get(data_url_ms, timeout=2), requests.get(data_url_bo, timeout=2)

    def append_by_kafka(self, market_situations_path=None, buy_offer_path=None):
        ########## use kafka example files
        if market_situations_path and buy_offer_path:
            self.append_by_csvs(market_situations_path, buy_offer_path)
            return
        #############

        try:
            ms, bo = self.download_kafka_files()
        except Exception as e:
            logging.warning('Could not download data from kafka: {}'.format(e))
            return
        if ms.status_code != 200 or bo.status_code != 200:
            logging.warning("Kafka download failed")
            return

        situation_data = csv.DictReader(ms.text.split("\n"))
        for line in situation_data:
            self.append_marketplace_situations(line)
        buy_offer_data = csv.DictReader(bo.text.split("\n"))
        for line in buy_offer_data:
            self.append_sales(line)


def learn_from_csvs(token):
    logging.debug('Reading csv files')
    market_situation = []
    sales = []
    with open(INITIAL_MARKETSITUATION_CSV_PATH, 'r') as csvfile:
        fieldnames = ['amount', 'merchant_id', 'offer_id', 'price', 'prime', 'product_id', 'quality', ' shipping_time_prime', 'shipping_time_standard', 'timestamp', 'triggering_merchant_id', 'uid']
        situation_reader = csv.DictReader(csvfile, fieldnames=fieldnames)
        for situation in situation_reader:
            market_situation.append(situation)

    with open(INITIAL_BUYOFFER_CSV_PATH, 'r') as csvfile:
        fieldnames = ['amount', 'consumer_id', 'http_code', 'left_in_stock', 'merchant_id', 'offer_id', 'price', 'product_id', 'quality', 'timestamp', 'uid']
        sales_reader = csv.DictReader(csvfile, fieldnames=fieldnames)
        for sale in sales_reader:
            sales.append(sale)
    logging.debug('Finished reading of csv files')
    merchant_id = sales[0]['merchant_id']
    return aggregate(market_situation, sales, merchant_id)


def download_data_and_aggregate(merchant_token, merchant_id):
    # Dont know, if we need that URL at some point
    # 'http://vm-mpws2016hp1-05.eaalab.hpi.uni-potsdam.de:8001'
    PricewarsRequester.add_api_token(merchant_token)
    logging.debug('Downloading files from Kafka ...')
    kafka_url = os.getenv('PRICEWARS_KAFKA_REVERSE_PROXY_URL', 'http://127.0.0.1:8001')
    kafka_api = KafkaApi(host=kafka_url)
    csvs = {'marketSituation': None, 'buyOffer': None}
    topics = ['marketSituation', 'buyOffer']

    for topic in topics:
        try:
            data_url = kafka_api.request_csv_export_for_topic(topic)
            # TODO error handling for empty csvs
            resp = requests.get(data_url, timeout=2)
            reader = csv.DictReader(resp.text.split("\n"))
            csvs[topic] = [line for line in reader]
        except Exception as e:
            logging.warning('Could not download data for topic {} from kafka: {}'.format(topic, e))
    logging.debug('Download finished')
    if csvs[topics[0]] and csvs[topics[1]]:
        # try:
        return aggregate(csvs['marketSituation'], csvs['buyOffer'], merchant_id)
        # except Exception as e:
        #     print(csvs)
    else:
        logging.info('Received empty csv files!')
        return None


def aggregate(market_situation, sales, merchant_id):
    vectors = dict()
    logging.debug('Starting data aggregation')

    timestamp = market_situation[0]['timestamp']
    current_offers = []
    sales_counter = 0
    for situation in market_situation:
        if timestamp == situation['timestamp']:
            current_offers.append(situation)
        else:
            own_sales = []
            # import pdb; pdb.set_trace()

            while sales_counter < len(sales) and to_timestamp(sales[sales_counter]['timestamp']) < to_timestamp(situation['timestamp']):
                if sales[sales_counter]['http_code'][0] == '2':
                    own_sales.append(sales[sales_counter])
                sales_counter += 1
            vectors = calculate_features(current_offers, own_sales, merchant_id, vectors)
            timestamp = situation['timestamp']
            current_offers.clear()
            current_offers.append(situation)
    logging.debug('Finished data aggregation')
    return vectors


def calculate_features(offers, sales, merchant_id, vectors):
    competitor_offers = defaultdict(dict)
    own_offers = defaultdict(dict)
    for offer in offers:
        if offer['merchant_id'] == merchant_id:
            own_offers[offer['product_id']][offer['offer_id']] = (offer['price'], offer['quality'])
        else:
            competitor_offers[offer['product_id']][offer['offer_id']] = (offer['price'], offer['quality'])

    items_sold = [sold['offer_id'] for sold in sales]

    for product_id, offers in own_offers.items():
        # Layout: Ownprice, quality, price_rank, (amount_of_offers), average_price_on_market, distance_to_cheapest, (amount_of_comp)
        for offer_id, values in offers.items():
            features = []
            own_price = float(values[0])
            features.append(own_price)
            features.append(int(values[1]))
            price_list = [float(offer[0]) for offer in competitor_offers[product_id].values()]
            # TODO remove the shit below, when fixed
            if not price_list:
                continue
            features.append(calculate_price_rank(price_list, own_price))
            features.append(len(competitor_offers[product_id].values()))
            features.append(sum(price_list) / len(price_list))
            features.append(own_price - min(price_list))

            sold = 1 if offer_id in items_sold else 0

            if not vectors.get(product_id):
                vectors[product_id] = ([], [])
            vectors[product_id][0].append(features)
            vectors[product_id][1].append(sold)
    return vectors


def calculate_price_rank(price_list, own_price):
    price_rank = 1
    for price in price_list:
        if own_price > price:
            price_rank += 1
    return price_rank


def to_timestamp(timestamp):
    return datetime.datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S.%fZ")


def calculate_min_price(offers):
    price, quality = zip(*list(offers.values()))
    return min(list(price))


def calculate_merchant_id_from_token(token):
    return base64.b64encode(hashlib.sha256(
        token.encode('utf-8')).digest()).decode('utf-8')


def extract_features_from_offer_snapshot(price, offers, merchant_id,
                                         product_id):
    offers = [x for x in offers if product_id == x.product_id]
    features = [price]
    own_offer = [x for x in offers if x.merchant_id == merchant_id]
    features.append(own_offer[0].quality)
    price_list = [x.price for x in offers if x.merchant_id != merchant_id]
    features.append(calculate_price_rank(price_list, price))
    features.append(len(price_list))
    features.append(sum(price_list) / len(price_list))
    features.append(price - min(price_list))
    return features
