"""
=====================================================================================

Game integration API

This is the API used for the integration of our smart contract functionality into a game.
This API is built to be run in the game code, and should only be accessible via this method.
The API utilizes a queue based system, allowing all the transactions to occur in order,
without impeding on the NEO network.

https://github.com/LootToken/LootMarket/wiki/REST-API-Documentation

Author: Christopher Luke Poli - @poli
Email: aus.poli1@gmail.com

======================================================================================

"""

# Imports
import os
import sys
import json
import time
import argparse
import binascii
import threading
import logging
import json
import logzero
import redis

from functools import wraps
from json.decoder import JSONDecodeError
from tempfile import NamedTemporaryFile
from collections import defaultdict
from klein import Klein, resource
from logzero import logger
from Crypto import Random
from twisted.web.resource import Resource
from twisted.internet import reactor, task, endpoints
from twisted.web.server import Request, Site
from twisted.python import log
from twisted.internet.protocol import Factory
from twisted.internet.endpoints import TCP4ClientEndpoint
from twisted.internet import protocol, reactor

# Neo imports
from neo.SmartContract.Contract import Contract
from neo.Network.NodeLeader import NodeLeader
from neo.Implementations.Blockchains.LevelDB.LevelDBBlockchain import LevelDBBlockchain
from neo.Core.Blockchain import Blockchain
from neo.Settings import settings
from neo.Wallets.Wallet import KeyPair
from neocore import UInt160
from neocore.Cryptography.Crypto import Crypto

# To create a transaction_key.
from uuid import uuid4
from uuid import UUID

# Import the smart contract queue handler.
from LootMarketHandler import LootSmartContract

# Allow importing 'neo' from parent path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.abspath(os.path.join(current_dir, ".."))
sys.path.insert(0, parent_dir)

# API port on our server - 8090
API_PORT = os.getenv("API_PORT", "8090")

# The hash our of smart contract.
# Currently deployed on CoZ testnet.
CONTRACT_HASH = os.getenv("LootTokenHash", "55bfd190812d608e696f5c7c751c83a667c82364")

# Which protocol to configure to: privnet/testnet/mainnet.
PROTOCOL_CONFIG = os.path.join(parent_dir, "protocol.faucet.json")

# Location of the wallet file and password.
WALLET_FILE = "/home/ec2-user/neo-python/loot.wallet"
WALLET_PWD = os.getenv("WALLET_PWD", "password123")

# Log file settings.
LOGFILE = os.path.join(parent_dir, "LootToken.log")
logzero.logfile(LOGFILE, maxBytes=1e7, backupCount=3)

# API error codes.
STATUS_ERROR_AUTH_TOKEN = 1
STATUS_ERROR_JSON = 2
STATUS_ERROR_GENERIC = 3

# Authorization token.
IS_DEV = True
API_AUTH_TOKEN = os.getenv("API_AUTH_TOKEN")
if not API_AUTH_TOKEN:
    if IS_DEV:
        API_AUTH_TOKEN = "test-token"
    else:
        raise Exception("No API_AUTH_TOKEN environment variable found")

# Setup the smart contract and cache.
smart_contract = LootSmartContract(CONTRACT_HASH, WALLET_FILE, WALLET_PWD)
redis_cache = redis.StrictRedis(host='localhost', port=6379, db=0)

# Setup web app.
app = Klein()


#region Decorators

def authenticated(func):
    """ @authenticated decorator, which ensures the request has the correct access token. """

    @wraps(func)
    def wrapper(request, *args, **kwargs):
        # Make sure the Authorization header is present.
        if not request.requestHeaders.hasHeader("Authorization"):
            request.setHeader('Content-Type', 'application/json')
            request.setResponseCode(403)
            return build_error(STATUS_ERROR_AUTH_TOKEN, "Missing Authorization header")

        # Make sure the Authorization header is valid.
        user_auth_token = str(request.requestHeaders.getRawHeaders("Authorization")[0])

        if user_auth_token != "Bearer %s" % API_AUTH_TOKEN:
            request.setHeader('Content-Type', 'application/json')
            request.setResponseCode(403)
            return build_error(STATUS_ERROR_AUTH_TOKEN, "Wrong auth token")

        # If all good, proceed to request handler.
        return func(request, *args, **kwargs)

    return wrapper


def json_response(func):
    """ @json_response decorator adds header and dumps response object. """

    @wraps(func)
    def wrapper(request, *args, **kwargs):
        res = func(request, *args, **kwargs)
        request.setHeader('Content-Type', 'application/json')
        return json.dumps(res) if isinstance(res, dict) else res

    return wrapper


def catch_exceptions(func):
    """ @catch_exceptions decorator which handles generic exceptions in the request handler """

    @wraps(func)
    def wrapper(request, *args, **kwargs):
        try:
            res = func(request, *args, **kwargs)
        except Exception as e:
            logger.exception(e)
            request.setResponseCode(500)
            request.setHeader('Content-Type', 'application/json')
            return build_error(STATUS_ERROR_GENERIC, str(e))
        return res

    return wrapper

# endregion

# region Helper Methods


def request_header(request):
    """ If running a web browser based game, enable CORS. """
    request.setHeader('Access-Control-Allow-Origin', '*')
    request.setHeader('Access-Control-Allow-Methods', 'GET,POST')
    request.setHeader('Access-Control-Allow-Headers', 'x-prototype-version,x-requested-with,Authorization')
    request.setHeader('Access-Control-Max-Age', 2520)
    request.setHeader('Content-type', 'application/json')


def build_error(error_code, error_message, to_json=True):
    """ Builder for generic errors. """
    res = {
        "errorCode": error_code,
        "errorMessage": error_message
    }
    return json.dumps(res) if to_json else res


class UUIDEncoder(json.JSONEncoder):
    def default(self, obj):
        """Helper method for decoding the uuid4 transaction key to JSON format."""
        if isinstance(obj, UUID):
            # If the obj is UUID, we simply return the value of UUID.
            return obj.hex
        return json.JSONEncoder.default(self, obj)

# endregion

# region General

@app.route('/')
def index(request):
    """ The API index. """
    return "This is the API used for LootClicker. \nPlease visit LootClicker.io for more information."


@app.route('/search/<transaction_key>/<address>/<operation>')
@json_response
@catch_exceptions
@authenticated
def search_transaction(request, transaction_key, address, operation):
    """
    Used for in game notification integration.
    Upon any API call which invokes a smart contract operation, a transaction key (UUID4) is sent back in the response.
    This transaction key can be used to call this function to check:
        1. Whether the transaction was found on the blockchain.
        2. Whether the smart contract operation invoked was successful.
    The currently searchable operations:  give_items,remove_item,buy_offer,put_offer,cancel_offer,transfer_item.

    :param request:Request object which gets passed into every route function.
    :param transaction_key:str The transaction key to query.
    :param address:str The address of the player who made this request.
    :param operation:str Which smart contract operation to check if was successfully completed.
    :returns
        tx_found:bool Whether the transaction was found.
        operation_complete:bool Whether the smart contract invocation was successful in operation.
    """
    request_header(request)

    # Search to see if we can find the transaction on the blockchain.
    smart_contract.search_tx(transaction_key)

    # Get if the transaction was found from the redis_cache.
    was_transaction_found = redis_cache.get("tx%s" % transaction_key)

    # If the transaction was found we can decode it.
    if was_transaction_found is not None:
        was_transaction_found = was_transaction_found.decode("utf-8")

    operation_complete = None
    # If the transaction was found we can check if the operation was successfully completed.
    if was_transaction_found == "True":
        operation_complete = redis_cache.get(operation+"%s" % address)
        if operation_complete is not None:
            operation_complete = bool(int.from_bytes(operation_complete, byteorder='little'))

    return {
        "tx_found": was_transaction_found,
        "operation_complete": operation_complete
    }


# endregion

#region Inventory

@app.route('/inventory/<address>')
@catch_exceptions
@json_response
@authenticated
def get_inventory(request, address):
    """
    Test invoke the contract to query the inventory of the address on a marketplace.

    :param address:str The address to query for items.

    :returns
        address:str The address of a player, returned to the game to ensure we have the correct address.
        inventory:str The items the inventory of the address contains.
    """
    request_header(request)

    # Test invoke the operation to get a result.
    smart_contract.test_invoke("market","get_inventory",address)

    # Get the inventory from cache.
    inventory = str(redis_cache.get("inventory:%s" % address))

    return {
        "address": address,
        "inventory": inventory
    }


@app.route('/inventory/give/<address>/<item_ids>')
@catch_exceptions
@authenticated
@json_response
def give_items(request, address, item_ids):
    """
    Add to the handler queue the smart contract operation to give items to the address on a marketplace.

    :param address:str The address to give items.
    :param item_ids:str A string containing a list of items.
    :return:
        transaction_key:str A key which can be used to search for the details of a transaction from the game.
    """
    request_header(request)

    # Split the items and convert each element to an integer.
    args = [ int(item_id) for item_id in item_ids.split(',') ]

    # Insert the address we are giving the items to the front.
    args.insert(0,address)

    # Generate a UUID4 transaction key.
    transaction_key = uuid4()
    transaction_key = UUIDEncoder.default(None,transaction_key)

    # Add the operation to the smart contract handler queue.
    smart_contract.add_invoke("give_items", transaction_key, args)

    return {
        "transaction_key": transaction_key
    }


@app.route('/inventory/remove/<address>/<item_id>')
@catch_exceptions
@authenticated
@json_response
def remove_item(request, address, item_id):
    """
    Add to the queue the smart contract operation to remove an item from an address.

    :param address:str The address to remove the item from.
    :type item_id:int The item to remove from the address.
    :return
        transaction_key:str A key which can be used to search for the details of a transaction from the game.
    """
    request_header(request)

    # Generate a UUID4 transaction key.
    transaction_key = uuid4()
    transaction_key = UUIDEncoder.default(None,transaction_key)

    args = [address,item_id]
    # Add the operation to the smart contract handler queue.
    smart_contract.add_invoke("remove_items",transaction_key, args)

    return {
        "transaction_key": transaction_key
    }


@app.route('/inventory/trade/<address_from>/<address_to>/<item_id>')
@catch_exceptions
@authenticated
@json_response
def transfer_item(request, address_from, address_to, item_id):
    """
    Add to the queue the smart contract operation to transfer an item from an address to another address.

    :param address_from:str The address sending the item.
    :param address_to:str The address receiving the item.
    :param item_id:int The id of the item being sent.
    :return:
        transaction_key:str A key which can be used to search for the details of a transaction from the game.
    """
    request_header(request)

    # Generate a UUID4 transaction key.
    transaction_key = uuid4()
    transaction_key = UUIDEncoder.default(None,transaction_key)

    # Add the operation to the smart contract handler queue.
    args = [address_from,address_to,item_id]
    smart_contract.add_invoke("transfer_item",transaction_key, args)

    return {
        "transaction_key": transaction_key
    }
# endregion

# region Marketplace

@app.route('/market/owner/<marketplace>')
@catch_exceptions
@json_response
def marketplace_owner(request, marketplace):
    """
    Test invoke the contract operation to query the owner of a marketplace.

    :param marketplace: The name of the marketplace to query to owner of.
    :returns:
        marketplace:str The name of the marketplace searched for.
        owner:str The address of the owner of the marketplace.
    """
    request_header(request)
    # Test invoke the contract to query the owner of the contract.
    smart_contract.test_invoke("general", "marketplace_owner", marketplace)

    # Get the stored owner from redis, decode if not None, and return the details.
    r_owner = redis_cache.get("owner:%s" % marketplace)
    if r_owner is not None:
        r_owner = r_owner.decode("utf-8")

    return {
        "marketplace": marketplace,
        "owner": r_owner
    }


@app.route('/market/buy/<address>/<offer_id>')
@json_response
@authenticated
def buy_offer(request, address, offer_id):
    """
    Add to the handler queue the smart contract operation to buy an offer on a marketplace.

    :param address: The address of the player wanting to buy an offer.
    :param offer_id: The id of the offer the player wants to buy.
    :return
        transaction_key:str A key which can be used to search for the details of a transaction from the game.
    """
    request_header(request)

    # Offer_id is sent in format, e.g. 'offer0', need to convert to 'offer\x00' for contract.
    index = offer_id.split('r', 1)
    p = int.to_bytes(int(index[1]), 1, 'little')
    p = str(p).lstrip('b').lstrip('\'').rstrip('\'')
    offer_id_s = 'offer' + p

    # Generate a unique UUID4 transaction key.
    transaction_key = uuid4()
    transaction_key = UUIDEncoder.default(None,transaction_key)

    # Construct the args and add the "buy" operation to the smart contract handler queue.
    args = [address,offer_id_s]
    smart_contract.add_invoke("buy_offer",transaction_key, args)

    return {
        "transaction_key": transaction_key
    }


@app.route('/market/put/<address>/<item_id>/<price>')
@catch_exceptions
@authenticated
@json_response
def put_offer(request, address, item_id, price):
    """
    Add to the handler queue the smart contract operation to put an offer on a marketplace.

    :param address:str The address of the player putting up an offer.
    :param item_id:int The id of the item the player wants to put up for offer.
    :param price:int The price of the item in LOOT the player has selected.
    :return
        transaction_key:str A key which can be used to search for the details of a transaction from the game.
    """
    request_header(request)

    # Generate a unique UUID4 transaction key.
    transaction_key = uuid4()
    transaction_key = UUIDEncoder.default(None,transaction_key)

    # Construct the args and add the "put" operation to the smart contract handler queue.
    args = [address,item_id,price]
    smart_contract.add_invoke("put_offer", transaction_key, args)

    return {
        "transaction_key": transaction_key
    }




@app.route('/market/cancel/<address>/<offer_id>')
@json_response
@authenticated
def cancel_offer(request, address, offer_id):
    """
    Add to the handler queue the smart contract operation to cancel an offer on a marketplace.

    :param address: The address of the player who wants to cancel the offer.
    :param offer_id: The offer the player wants to cancel.
    :return
        transaction_key:str A key which can be used to search for the details of a transaction from the game.
    """
    request_header(request)

    # Offer_id is sent in format, e.g. 'offer0', need to convert to 'offer\x00' for contract.
    index = offer_id.split('r', 1)
    p = int.to_bytes(int(index[1]), 1, 'little')
    p = str(p).lstrip('b').lstrip('\'').rstrip('\'')
    offer_id_s = 'offer' + p

    # Generate a UUID4 transaction key.
    transaction_key = uuid4()
    transaction_key = UUIDEncoder.default(None,transaction_key)

    # Construct the args and add the "cancel" operation to the smart contract handler queue.
    args = [address,offer_id_s]
    smart_contract.add_invoke("cancel_offer",transaction_key, args)

    return {
        "transaction_key": transaction_key
    }

@app.route('/market/get')
@catch_exceptions
@authenticated
@json_response
def get_offers(request):
    """
    Test invoke the contract operation to query the offers on a marketplace.

    :returns
        offers:list The list of offer ids retrieved from a marketplace.
        timeOffersUpdated:str The time the offers were last updated at.
    """
    request_header(request)

    # Test invoke the smart contract to get the offers that are on a marketplace.
    smart_contract.test_invoke("market","get_all_offers")

    # Get the offers and the time updated from the redis cache and return them.
    r_offers = redis_cache.get("offers").decode("utf-8")
    r_updated_at = redis_cache.get("timeOffersUpdated").decode("utf-8")

    return {
        "offers": r_offers,
        "timeOffersUpdated": r_updated_at
    }


@app.route('/market/get/<offer_id>')
@catch_exceptions
@authenticated
@json_response
def get_offer(request, offer_id):
    """
    Test invoke the contract to query the details of an offer on a marketplace.

    :param offer_id: The id of the offer on a marketplace.
    :return
        offer:list A list containing the information about the offer retrieved.
    """
    request_header(request)

    # Offer_id is sent in format, e.g. 'offer1', need to convert to e.g. 'offer\x01' for contract.
    index = offer_id.split('r', 1)
    p = int.to_bytes(int(index[1]), 1, 'little')
    p = str(p).lstrip('b').lstrip('\'').rstrip('\'')
    offer_id_s = 'offer' + p

    # Test invoke contract with the offer_id.
    smart_contract.test_invoke("offer","get_offer", offer_id_s)

    # Get the offer information from the redis cache.
    r_offer = redis_cache.get(offer_id).decode("utf-8")

    return {
        "offer": r_offer
    }

#endregion

# region Wallet

@app.route('/wallet/<address>')
@catch_exceptions
@authenticated
@json_response
def loot_balance(request, address):
    """
    Returns the LOOT balance of an address.

    :param address:str The address to query the LOOT of.
    :return
        balance:int The LOOT balance of the address.
    """
    request_header(request)

    # Test invoke the contract to get the balance.
    smart_contract.test_invoke("general", "balance_of", address)

    # Get the balance from the cache and return it.
    balance = redis_cache.get("balance:%s" % address).decode("utf-8")

    return {
        "balance": balance
    }


@app.route('/wallets/create')
@catch_exceptions
@authenticated
@json_response
def create_wallet(request):
    """
    Creates a NEP-2 key and address.
    Intended functionality is to give the player a way to access a marketplace.

    :returns:
        address:str The created address.
        nep2-key:str The created NEP-2 key.
    """
    request_header(request)
    try:
        body = json.loads(request.content.read().decode("utf-8"))
    except JSONDecodeError as e:
        request.setResponseCode(400)
        return build_error(STATUS_ERROR_JSON, "JSON Error: %s" % str(e))

    # Fail if no password in the request body.
    if not "password" in body:
        request.setResponseCode(400)
        return build_error(STATUS_ERROR_JSON, "No password in request body.")

    # Fail if password is not at least 8 characters.
    pwd = body["password"]
    if len(pwd) < 8:
        request.setResponseCode(400)
        return build_error(STATUS_ERROR_JSON, "Password needs a minimum length of 8 characters.")

    private_key = bytes(Random.get_random_bytes(32))
    key = KeyPair(priv_key=private_key)

    return {
        "address": key.GetAddress(),
        "nep2_key": key.ExportNEP2(pwd)
    }


@app.route('/wallet/claim_gas')
@catch_exceptions
@authenticated
def claim_gas(request):
    """ Claim the gas in the API wallet. """
    request_header(request)
    smart_contract.claim_gas()
    return "Claimed gas!"


# endregion

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", action="store", help="Config file (default. %s)" % PROTOCOL_CONFIG,
                        default=PROTOCOL_CONFIG)
    args = parser.parse_args()
    settings.setup(args.config)
    #settings.setup_privnet()
    logger.info("Starting api.py")
    logger.info("Config: %s", args.config)
    logger.info("Network: %s", settings.net_name)

    # Get the blockchain up and running.
    blockchain = LevelDBBlockchain(settings.LEVELDB_PATH)
    Blockchain.RegisterBlockchain(blockchain)
    reactor.suggestThreadPoolSize(15)
    NodeLeader.Instance().Start()
    dbloop = task.LoopingCall(Blockchain.Default().PersistBlocks)
    dbloop.start(.1)
    Blockchain.Default().PersistBlocks()
    try:
        # Hook up Klein API to Twisted reactor
        endpoint_description = "tcp:port=%s:interface=0.0.0.0" % "8090"
        endpoint = endpoints.serverFromString(reactor, endpoint_description)
    except Exception as err:
        print(err)

    endpoint.listen(Site(app.resource()))

    # Start the smart contract thread
    smart_contract.start()

    # Helper for periodic log output.
    def log_infos():
        while True:
            logger.info("Block %s / %s", str(Blockchain.Default().Height), str(Blockchain.Default().HeaderHeight))
            time.sleep(60)

    t = threading.Thread(target=log_infos)
    t.setDaemon(True)
    t.start()

    # reactor.callInThread(sc_queue.run)
    reactor.run()







