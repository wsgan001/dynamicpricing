import base64
import hashlib
import logging
import math
import os
import pickle
import traceback
from typing import List

import pandas as pd
import sys

from merchant_sdk.api import KafkaApi, PricewarsRequester
from merchant_sdk.models import Offer

NUM_OF_FEATURES = 16


# TODO: adapt to new downloading process
def download_data(merchant_token):
    # Dont know, if we need that URL at some point
    # 'http://vm-mpws2016hp1-05.eaalab.hpi.uni-potsdam.de:8001'
    PricewarsRequester.add_api_token(merchant_token)
    logging.debug('Downloading files from Kafka ...')
    kafka_url = os.getenv('PRICEWARS_KAFKA_REVERSE_PROXY_URL', 'http://127.0.0.1:8001')
    kafka_api = KafkaApi(host=kafka_url)
    csvs = {'marketSituation': None, 'buyOffer': None}
    for topic in ['marketSituation', 'buyOffer']:
        try:
            data_url = kafka_api.request_csv_export_for_topic(topic)
            # TODO do we really need panda? Isnt the standard csv reader sufficient?
            csvs[topic] = pd.read_csv(data_url)
        except pd.io.common.EmptyDataError as e:
            logging.warning('Kafka returned an empty csv for topic {}'.format(topic))
            return None
        except Exception as e:
            logging.warning('Could not download data for topic {} from kafka: {}'.format(topic, e))
            return None
    logging.debug('Download finished')
    return csvs


def calculate_price_rank(price_list, own_price):
    price_rank = 1
    for price in price_list:
        if own_price > price:
            price_rank += 1
    return price_rank


def calculate_min_price(offers):
    price, quality = zip(*list(offers.values()))
    return min(list(price))


def calculate_merchant_id_from_token(token):
    return base64.b64encode(hashlib.sha256(
        token.encode('utf-8')).digest()).decode('utf-8')


def calculate_performance(sales_probabilities: List[float], sales: List[int], feature_count: int):
    try:
        ll1, ll0 = calculate_aic(sales_probabilities, sales, feature_count)
        calculate_mcfadden(ll1, ll0)
        precision_recall(sales_probabilities, sales)
    except ValueError:
        logging.error("Error in performance calculation!")
        traceback.print_exc(file=sys.stdout)



def calculate_aic(sales_probabilities: List[float], sales: List[int], feature_count: int):
    # sales_probabilities: [0.35, 0.29, ...]
    # sales: [0, 1, 1, 0, ...]
    # feature_count: int


    # Für jede Situation:
    # verkauft? * log(verkaufswahrsch.) + (1 - verkauft?) * (1 - log(1-verkaufswahrsch.))
    # var LL  = sum{i in 1..B} ( y[i]*log(P[i]) + (1-y[i])*log(1-P[i]) );

    ll = 0

    # Nullmodel: Average sales probability based on actual sales
    # Some stuff to read about it:
    # https://stats.idre.ucla.edu/other/mult-pkg/faq/general/faq-what-are-pseudo-r-squareds/
    # http://www.karteikarte.com/card/2013125/null-modell

    ll0 = 0

    average_sales = sum(sales) / len(sales)

    for i in range(len(sales)):
        ll += sales[i] * math.log(sales_probabilities[i]) + \
              (1 - sales[i]) * (math.log(1 - sales_probabilities[i]))
        ll0 += sales[i] * math.log(average_sales) + \
               (1 - sales[i]) * (math.log(1 - average_sales))

    aic = - 2 * ll + 2 * feature_count

    logging.info('Log likelihood is: {}'.format(ll))
    logging.info('LL0 is: {}'.format(ll0))
    logging.info('AIC is: {}'.format(aic))

    return ll, ll0


def calculate_mcfadden(ll1, ll0):
    mcf = 1 - ll1 / ll0
    logging.debug('Hint: 0.2 < mcf < 0.4 is a good fit (higher is good)')
    logging.info('McFadden R squared is: {}'.format(mcf))


def precision_recall(sales_probabilities, sales):
    tp = 0
    fp = 0
    fn = 0

    av = sum(sales_probabilities) / len(sales_probabilities)

    for i in range(len(sales)):
        if sales_probabilities[i] > av:
            if sales[i] == 1:
                tp += 1
            else:
                fp += 1
        elif sales[i] == 0:
            fn += 1

    precision = tp / (tp + fp)
    recall = tp / (tp + fn)
    logging.warning('######### Precision/Recall might be wrong #########')
    logging.info('Precision is: {}'.format(precision))
    logging.info('Recall is: {}'.format(recall))


def extract_features(offer_id: str, offer_list: List[Offer]):
    current_offer = [x for x in offer_list if offer_id == x.offer_id][0]
    other_offers = [x for x in offer_list if offer_id != x.offer_id]

    price_rank = 1
    quality_rank = 1
    shipping_time_rank = 1

    for oo in other_offers:
        if float(oo.price) < float(current_offer.price):
            price_rank += 1
        if int(oo.quality) < int(current_offer.quality):
            quality_rank += 1
        if int(oo.shipping_time['standard']) < int(current_offer.shipping_time['standard']):
            shipping_time_rank += 1

    price_differences = calculate_price_differences(float(current_offer.price),
                                                    other_offers)

    # if new features are added, update NUM_OF_FEATURES variable!
    features = [price_rank,
                quality_rank,
                shipping_time_rank,
                len(offer_list), # amount_offers
                1 if current_offer.prime == 'True' else 0, # prime
                price_differences[1], # price_diff_to_min_in_%
                price_differences[3], # price_diff_to_2nd_min_in_%
                price_differences[5], # price_diff_to_3rd_min_in_%

                # disable following for general model
                float(current_offer.price), # price
                int(current_offer.quality), # quality
                int(current_offer.shipping_time['standard']), # shipping_time
                calculate_average_price(other_offers), # avg_price
                calculate_average_price(offer_list), # avg_price_with_own_offer
                price_differences[0], # price_diff_to_min
                price_differences[2], # price_diff_to_2nd_min
                price_differences[4] # price_diff_to_3rd_min
                ]
    # import pdb; pdb.set_trace()
    return features


def calculate_price_differences(own_price, other_offers):
    price_list = sorted([float(x.price) for x in other_offers])
    result = []
    for i in [0, 1, 2]:
        if i > len(price_list):
            result.extend([0, 0])
            continue
        diffs = calculate_price_difference(own_price, price_list[i],
                                           price_list[-1])
        result.extend(diffs)
    return result


def calculate_price_difference(price1, price2, max_price):
    diff = price1 - price2
    if price1 <= price2:
        diff_in_percent = 0.
    elif price1 >= max_price:
        diff_in_percent = 1.
    else:
        diff_in_percent = (price1 - price2) / (max_price - price2)
    return [diff, diff_in_percent]


def calculate_average_price(offers):
    price_list = [float(x.price) for x in offers]
    return sum(price_list) / len(price_list)


def load_history(file):
    with open(file, 'rb') as m:
        return pickle.load(m)


def save_training_data(data, file):
    with open(file, 'wb') as m:
        pickle.dump(data, m)
