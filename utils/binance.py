import time, hmac, hashlib, requests, urllib.parse

MAIN_BASE = 'https://fapi.binance.com'
TEST_BASE = 'https://testnet.binancefuture.com'
MAIN_WS = 'wss://fstream.binance.com/ws'
TEST_WS = 'wss://stream.binancefuture.com/ws'

class BinanceUM:
    def __init__(self, api_key: str, api_secret: str, testnet: bool = True):
        self.api_key = (api_key or '').strip()
        self.api_secret = (api_secret or '').strip().encode()
        self.base = TEST_BASE if testnet else MAIN_BASE
        self.ws_base = TEST_WS if testnet else MAIN_WS
        self._offset = None
        self.session = requests.Session()
        self.session.headers.update({'Content-Type': 'application/x-www-form-urlencoded'})


    def _headers(self):
        return {'X-MBX-APIKEY': self.api_key}

    def _server_time(self):
        try:
            r = self.session.get(self.base + '/fapi/v1/time', timeout=10)
            if r.status_code == 200:
                return int(r.json().get('serverTime', 0))
        except Exception:
            pass
        return None

    def _timestamp_ms(self):
        if self._offset is None:
            st = self._server_time()
            if st: self._offset = st - int(time.time()*1000)
            else: self._offset = 0
        return int(time.time()*1000) + self._offset

    def _signed_params(self, params: dict):
        ordered = list(params.items())
        query = urllib.parse.urlencode(ordered, doseq=True)
        sig = hmac.new(self.api_secret, query.encode(), hashlib.sha256).hexdigest()
        ordered.append(('signature', sig))
        return ordered

    def _request(self, method, path, params=None, signed=False):
        url = self.base + path
        params = params or {}
        
        headers = self._headers() if signed else None

        if signed:
            params['timestamp'] = self._timestamp_ms()
            params.setdefault('recvWindow', 5000)
            send_params = self._signed_params(params)
        else:
            send_params = params

        retries = 3
        delay = 2
        timeout_duration = 20

        for i in range(retries):
            try:
                if method == 'GET':
                    r = self.session.get(url, params=send_params, headers=headers, timeout=timeout_duration)
                elif method == 'POST':
                    r = self.session.post(url, data=send_params, headers=headers, timeout=timeout_duration)
                elif method == 'DELETE':
                    r = self.session.delete(url, params=send_params, headers=headers, timeout=timeout_duration)
                else:
                    raise ValueError('Unsupported method')

                response_json = r.json()

                if r.status_code >= 400:
                    raise Exception(f"Binance API Error: {response_json.get('msg')} (Code: {response_json.get('code')})")

                if isinstance(response_json, dict) and response_json.get('code') and response_json.get('code') != 200:
                    raise Exception(f"Binance API Error: {response_json.get('msg')} (Code: {response_json.get('code')})")
                
                return response_json


            except (requests.exceptions.RequestException) as e:
                print(f"Request failed due to network error: {e}. Attempt {i + 1}/{retries}.")
                if i < retries - 1:
                    time.sleep(delay)
                else:
                    raise Exception(f"Request failed after {retries} attempts: {e}")
        
        raise Exception("Request failed after all retries.")


    # Public
    def exchange_info(self): return self._request('GET','/fapi/v1/exchangeInfo')
    def price(self, symbol): return self._request('GET','/fapi/v1/ticker/price',{'symbol':symbol})
    def time(self): return self._request('GET','/fapi/v1/time')
    def klines(self, symbol, interval, limit=1): return self._request('GET', '/fapi/v1/klines', {'symbol': symbol, 'interval': interval, 'limit': limit})


    # Signed
    def get_user_trades(self, symbol, start_time=None, limit=10):
        params = {'symbol': symbol, 'limit': limit}
        if start_time:
            params['startTime'] = start_time
        return self._request('GET', '/fapi/v1/userTrades', params, signed=True)

    def futures_balance(self):
        data=self._request('GET','/fapi/v2/balance', signed=True)
        for a in data:
            if a.get('asset')=='USDT': return float(a.get('availableBalance',0))
        return 0.0

    def set_margin_type(self, symbol, margin_type: str):
        try:
            margin_type = margin_type.upper()
            if margin_type not in ['ISOLATED', 'CROSSED']:
                raise ValueError("margin_type must be 'ISOLATED' or 'CROSSED'")
            return self._request('POST','/fapi/v1/marginType',{'symbol':symbol,'marginType':margin_type}, signed=True)
        except Exception as e:
            if 'No need to change margin type' in str(e): return {'msg':f'already {margin_type.lower()}'}
            raise

    def set_leverage(self, symbol, leverage):
        leverage=max(1,min(150,int(leverage)))
        return self._request('POST','/fapi/v1/leverage',{'symbol':symbol,'leverage':leverage}, signed=True)

    def set_hedge_mode(self, enable=True):
        try:
            return self._request('POST','/fapi/v1/positionSide/dual',{'dualSidePosition':'true' if enable else 'false'}, signed=True)
        except Exception as e:
            s=str(e)
            if 'No need to change position side' in s or 'code":-4059' in s:
                return {'msg':'already in desired hedge mode'}
            raise

    def position_risk(self, symbol=None):
        params={}
        if symbol: params['symbol']=symbol
        return self._request('GET','/fapi/v2/positionRisk', params, signed=True)

    def get_hedge_mode(self):
        try:
            d=self._request('GET','/fapi/v1/positionSide/dual', signed=True)
            return bool(d.get('dualSidePosition'))
        except Exception:
            return False

    def order_market(self, symbol, side, quantity, position_side=None, reduce_only=False):
        params={'symbol':symbol,'side':side,'type':'MARKET','quantity':quantity}
        if position_side:
            params['positionSide']=position_side
        if reduce_only:
            params['reduceOnly']='true'
        return self._request('POST','/fapi/v1/order', params, signed=True)

    def symbol_filters(self, symbol):
        info=self.exchange_info()
        lot=None; min_notional=None
        for s in info.get('symbols', []):
            if s.get('symbol')==symbol:
                for f in s.get('filters', []):
                    if f.get('filterType')=='LOT_SIZE':
                        lot={'stepSize':float(f.get('stepSize')), 'minQty':float(f.get('minQty'))}
                    if f.get('filterType')=='MIN_NOTIONAL':
                        try: min_notional=float(f.get('notional'))
                        except: pass
                break
        return lot, min_notional

    def round_lot_size(self, symbol, qty):
        info=self.exchange_info()
        for s in info.get('symbols', []):
            if s.get('symbol')==symbol:
                for f in s.get('filters', []):
                    if f.get('filterType')=='LOT_SIZE':
                        step=float(f.get('stepSize')); minQ=float(f.get('minQty'))
                        precision=max(0, str(step)[::-1].find('.'))
                        if step>=1: precision=0
                        q = round(qty / step) * step
                        q = max(q, minQ)
                        return float(f"{q:.{precision}f}")
        return qty