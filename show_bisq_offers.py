#!/usr/bin/env python3
#
# This creates 100 files in the current directory of the format bisq_N.txt where N is the maximum market distance percent.
# You must pass a config file as the first argument.

import functools
import requests
import hashlib
import hmac
import json
import math
import time
import sys
import re
import smtplib
import twitter
from email.mime.text import MIMEText
from babel import numbers
from coinbase.wallet.client import Client

DOCS="""
Notes:

Market distance is defined differently based on the offer type. \
For "Sells", a negative market distance means the offer is to sell at less than the market price. \
For "Buys", a negative market distance means the offer is to buy at greater than the market price. \
This means that a negative (or low) distance is generally a good deal for both types.

Current BTC, LTC, and ETH price comes from coinbase.com. Current DCR price comes from coinmarketcap.com.

Code for this tool is available at: https://github.com/valankar/arviraj
A Twitter bot with good offers is available at: https://twitter.com/BisqArviraj

Find this useful? Please consider donating:
BCH: 16VpFt7VS9qDbKiobPYo2dyAbo9kaZPmw9
BTC: 3JMg8bqgexYwXEwJiDncuBnoSAqGntkyS9
DCR: Dsodia7RaK1dwA3UvVbTtsRuH8zc4Bvs5oF
ETH: 0x30600Ba4A62903231681EdFE2f2e2Fe971077A3D
LTC: MEHS3ZpPLb3MZq5axjo5yWTfSpuw6xAtgS
"""
CONFIG={}
MARKET_DISTANCES=range(0, 101)
NOW=time.time()
CURRENCY_FORMAT=u'###0.00 ¤¤'
IGNORE_PAYMENT_METHODS=('F2F', 'CASH_DEPOSIT', 'US_POSTAL_MONEY_ORDER')


def send_twitter_notification(output, offer_id, criteria, trade_type):
    global CONFIG
    sent = offer_id + ' twitter ' + criteria['consumer_key']
    if sent in CONFIG['sent_notifications']:
       return
    CONFIG['sent_notifications'][sent] = True
    api = twitter.Api(consumer_key=criteria['consumer_key'],
                      consumer_secret=criteria['consumer_secret'],
                      access_token_key=criteria['access_token'],
                      access_token_secret=criteria['access_token_secret'])
    condensed = [trade_type]
    for line in output:
        if 'fee:' in line:
            continue
        if 'Age:' in line:
            continue
        line = line.replace(' from market', '')
        condensed.append(re.sub(r'\s+', ' ', line.strip()))
    tweet = '\n'.join(condensed)[:140]
    try:
        api.PostUpdate(tweet, verify_status_length=False)
    except:
        pass

def send_email_notification(output, offer_id, criteria, trade_type):
    global CONFIG
    sent = offer_id + ' email ' + criteria['email']
    if sent in CONFIG['sent_notifications']:
        return
    CONFIG['sent_notifications'][sent] = True
    msg = MIMEText('\n'.join([trade_type] + output))
    msg['Subject'] = criteria['subject']
    msg['From'] = criteria['from']
    msg['To'] = criteria['email']
    try:
        s = smtplib.SMTP(criteria['smtp_server'])
        s.sendmail(criteria['from'], [criteria['email']], msg.as_string())
        s.quit()
    except:
        pass

def send_notification(output, offer_id, payment_method, distance_from_market_percent, sale):
    global CONFIG
    for criteria in CONFIG['notifications']:
        if sale:
            trade_type = 'SELL'
            if 'sell' not in criteria['type']:
                continue
        else:
            trade_type = 'BUY'
            if 'buy' not in criteria['type']:
                continue
        if payment_method not in criteria['payment_method']:
            continue
        if criteria['distance'] < distance_from_market_percent:
            continue
        method = criteria['notification_method']
        if method == 'email':
            send_email_notification(output, offer_id, criteria, trade_type)
        elif method == 'twitter':
            send_twitter_notification(output, offer_id, criteria, trade_type)

def load_config():
    global CONFIG
    with open(sys.argv[1]) as config_file:
        CONFIG = json.load(config_file)
    try:
        with open(CONFIG['notification_state_file']) as f:
            CONFIG['sent_notifications'] = json.load(f)
    except:
        CONFIG['sent_notifications'] = {}

def save_notification_state():
    with open(CONFIG['notification_state_file'], 'w') as f:
        json.dump(CONFIG['sent_notifications'], f, indent=2, sort_keys=True)

def get_dcr_spot():
    global CONFIG
    url = 'https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest'
    parameters = {
        'id': '1168'
    }
    headers = {
        'Accepts': 'application/json',
        'X-CMC_PRO_API_KEY': CONFIG['coinmarketcap_api_key'],
    }
    session = requests.Session()
    session.headers.update(headers)
    response = session.get(url, params=parameters)
    data = json.loads(response.text)
    return float(data['data']['1168']['quote']['USD']['price'])

@functools.lru_cache(maxsize=None)
def get_bisq_tx_fee():
    fee = 0
    try:
        fee = int(requests.get(url='http://37.139.14.34:8080/getFees').json()['dataMap']['btcTxFee'])
    except requests.exceptions.ConnectionError:
        pass
    return fee

def get_fees(amount, distance):
    fee = get_bisq_tx_fee() * 200/100000000.
    maker = max(0.0002, 0.002 * amount * math.sqrt(distance)) + fee
    taker = max(0.0002, 0.003 * amount) + (3 * fee)
    return (maker, taker)

def get_range_or_value(first, second, format_str):
    if first == second:
        return format_str.format(first)
    else:
        return (format_str + ' - ' + format_str).format(first, second)

def shorten_trade_id(trade_id):
    return trade_id.split('-')[0]

def format_currency(value, currency):
    return numbers.format_currency(value, currency, CURRENCY_FORMAT)

def process_offer(offer, currency, market_price, distance, multiplier, sale):
    global CONFIG
    output = []
    price = float(offer['price'])
    distance_from_market_percent = ((price * multiplier) - market_price) / market_price * 100
    if not sale:
        distance_from_market_percent *= -1
    if distance_from_market_percent > distance:
        return []
    fiat = False
    if offer['payment_method'] in IGNORE_PAYMENT_METHODS:
        return []
    if offer['payment_method'] != 'BLOCK_CHAINS':
        output.append('\tPayment method: {}'.format(offer['payment_method']))
        volume = offer['amount']
        fiat = True
    else:
        volume = offer['volume']
    age = get_human_readable_time(NOW - int(offer['offer_date'] / 1000))
    output.append('\tOffer ID: {}'.format(shorten_trade_id(offer['offer_id'])))
    output.append('\tAmount: {} BTC'.format(get_range_or_value(float(offer['min_amount']), float(volume), '{}')))
    min_fee = get_fees(float(offer['min_amount']), abs(distance_from_market_percent))
    max_fee = get_fees(float(volume), abs(distance_from_market_percent))
    output.append('\tMaker fee: {} BTC'.format(get_range_or_value(min_fee[0], max_fee[0], '{:f}')))
    output.append('\tTaker fee: {} BTC'.format(get_range_or_value(min_fee[1], max_fee[1], '{:f}')))
    if fiat:
        price_for_one = price
        maximum = price * float(volume)
    else:
        price_for_one = price * multiplier
        maximum = multiplier * float(volume)
        currency = 'USD'
    try:
        if maximum < CONFIG['minimum_sale'][currency.lower()]:
            return []
    except KeyError:
        pass
    output.append('\tPrice for 1: {}'.format(format_currency(price_for_one, currency)))
    output.append('\tMaximum: {}'.format(format_currency(maximum, currency)))
    output.append('\tDistance from market: {:.2f}%'.format(distance_from_market_percent))
    output.append('\tAge: {}'.format(age))
    send_notification(output, offer['offer_id'], offer['payment_method'], distance_from_market_percent, sale)
    return output

def get_human_readable_time(seconds):
    d = int(seconds / (60 * 60 * 24))
    h = int((seconds % (60 * 60 * 24)) / (60 * 60))
    m = int((seconds % (60 * 60)) / 60)
    s = int(seconds % 60)
    if d:
        return '{:d}d'.format(d)
    if h:
        return '{:d}h'.format(h)
    if m:
        return '{:d}m'.format(m)
    return '{:d}s'.format(s)

def get_last_trade(bisq_last_trade, market_price, multiplier):
    price = float(bisq_last_trade['price'])
    trade_id = shorten_trade_id(bisq_last_trade['trade_id'])
    age = get_human_readable_time(NOW - int(bisq_last_trade['trade_date'] / 1000))
    distance_from_market_percent = ((price * multiplier) - market_price) / market_price * 100
    if multiplier == 1:
        price_text = ': {:.2f}'.format(price)
    else:
        price_text = ' in USD: {:.2f}'.format(price * multiplier)
    text = 'Last trade (ID: {}) price for 1{}, Distance from current market: {:.2f}%, Age: {}'.format(
            trade_id, price_text, distance_from_market_percent, age)
    return text

def write_offers(output_file, currency, bisq_market, market_price, distance, multiplier):
    sell_offers = []
    for offer in sorted(bisq_market['sells'], key=lambda x: float(x['volume']), reverse=True):
        output = process_offer(offer, currency, market_price, distance, multiplier, True)
        if output:
            sell_offers.append(output)

    buy_offers = []
    for offer in sorted(bisq_market['buys'], key=lambda x: float(x['volume']), reverse=True):
        output = process_offer(offer, currency, market_price, distance, multiplier, False)
        if output:
            buy_offers.append(output)

    if sell_offers or buy_offers:
        if sell_offers:
            output_file.write('\nSells\n')
            output_file.write('\n\n'.join(['\n'.join(x) for x in sell_offers]))
        if buy_offers:
            output_file.write('\nBuys\n')
            output_file.write('\n\n'.join(['\n'.join(x) for x in buy_offers]))

    output_file.write('\n')

def get_bisq_market_url(market):
    return('https://market.bisq.io/api/offers?market={}'.format(market))

def get_bisq_last_trade_url(market):
    return('https://market.bisq.io/api/trades?market={}&limit=1'.format(market))

@functools.lru_cache(maxsize=None)
def get_coinbase_spot(client, src, dst):
    return float(client.get_spot_price(currency_pair = '%s-%s' % (src, dst))['amount'])

load_config()
market_prices = {}
needs_conversion = {}
coinbase_client = Client(CONFIG['coinbase_api_key'], CONFIG['coinbase_api_secret'])
for market in CONFIG['markets']:
    (src, dst) = market.split('_')
    if dst == 'btc':
        if src == 'dcr':
            market_prices[market] = get_dcr_spot()
            continue
        dst = 'usd'
    market_prices[market] = get_coinbase_spot(coinbase_client, src, dst)

bisq_markets = {}
bisq_last_trades = {}
for market in CONFIG['markets']:
    bisq_markets[market] = requests.get(get_bisq_market_url(market)).json()[market]
    try:
        bisq_last_trades[market] = requests.get(get_bisq_last_trade_url(market)).json()[0]
    except IndexError:
        pass

for distance in MARKET_DISTANCES:
    f = open(CONFIG['distance_file_format'].format(distance), 'w')
    for market in CONFIG['markets']:
        (src, dst) = market.split('_')
        if dst == 'btc':
            dst = 'usd'
        f.write('Current {} price in {}: {:.2f}\n'.format(src.upper(), dst.upper(), market_prices[market]))
    f.write('\nBisq offers with market distance < {:d}%\n\n'.format(distance))

    for market in CONFIG['markets']:
        multiplier = 1
        (src, dst) = market.split('_')
        if dst == 'btc':
            multiplier = market_prices['btc_usd']
        try:
            last_trade = get_last_trade(bisq_last_trades[market], market_prices[market], multiplier)
        except KeyError:
            last_trade = 'no last trade found'
        f.write('{} Offers with {} ({})'.format(src.upper(), dst.upper(), last_trade))
        write_offers(f, dst.upper(), bisq_markets[market], market_prices[market], distance, multiplier)
        f.write('\n')

    f.write('Last updated: {}\n'.format(time.strftime('%c %Z', time.localtime(NOW))))
    f.writelines(DOCS)
    f.close()

save_notification_state()
