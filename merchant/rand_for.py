import argparse
import logging

from sklearn.ensemble import RandomForestRegressor

from MlMerchant import MLMerchant
from merchant_sdk import MerchantServer
from settings import Settings


class RandomForestMerchant(MLMerchant):
    def __init__(self):
        self.model = dict()
        super().__init__(Settings('rand_for_models.pkl'))

    def train_model(self, features):
        # TODO include time and amount of sold items to featurelist
        logging.debug('Start training')
        for product_id, vector_tuple in features.items():
            # I'm puttin n_estimators in constructor,
            # since this is a good point for improvement (btw. 10 is actually default)
            product_model = RandomForestRegressor(n_estimators=10)
            product_model.fit(vector_tuple[0], vector_tuple[1])
            self.model[product_id] = product_model
        logging.debug('Finished training')

    def predict(self, product_id, situations):
        # TODO: What happens if there is no such product_id ?
        return self.model[product_id].predict(situations)


if __name__ == "__main__":
    logging.getLogger().setLevel(logging.DEBUG)
    parser = argparse.ArgumentParser(
        description='PriceWars Merchant doing Random Forest Regression')
    parser.add_argument('--port',
                        type=int,
                        default=5102,
                        help='Port to bind flask App to, default is 5102')
    args = parser.parse_args()
    server = MerchantServer(RandomForestMerchant())
    app = server.app
    app.run(host='0.0.0.0', port=args.port)