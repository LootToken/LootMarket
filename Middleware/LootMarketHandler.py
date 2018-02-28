"""
=====================================================================================

The API uses this to handle the concurrent smart contract invokes.

Author: Christopher Luke Poli - @poli
Email: aus.poli1@gmail.com

=====================================================================================
"""

import struct
import time
import redis
import threading
import codecs
from datetime import datetime
from queue import Queue
from logzero import logger
from twisted.internet import task
from neocore import UInt160
from neo.Implementations.Wallets.peewee.UserWallet import UserWallet
from neo.Prompt.Commands.Invoke import InvokeContract, TestInvokeContract, test_invoke
from neo.Settings import settings
from neo.Core.Blockchain import Blockchain
from neocore.Cryptography.Crypto import Crypto
from neo.contrib.smartcontract import SmartContract
from neo.Prompt.Commands.Wallet import ClaimGas
from neo.VM.ScriptBuilder import ScriptBuilder
from neo.Prompt.Utils import parse_param

# Setup the blockchain task queue.
class LootMarketsSmartContract(threading.Thread):
    """
    Invoke queue is necessary for handling many concurrent smart contracts invokes.
    Many API calls want to initiate a smart contract operation, they add them
    to this queue, and they get processed in order.
    """
    # The name of the smart contract marketplace being used, this must be registered on the blockchain before use.
    marketplace = "LootClickerMarket"

    smart_contract = None
    contract_hash = None

    wallet_path = None
    wallet_pass = None

    # Stores offers that are trying to be cancelled/bought so we don't see them within the marketplace.
    # We do not want multiple people queuing up to buy the same item, or a cancelled item.
    # This will be removed from the cache as all transactions will be added to the queue and eventually invoked,
    # removing it on fail or success.
    cached_offers = []

    tx_in_progress = None

    # Queue items are always a tuple (operation_name, args)
    invoke_queue = None
    wallet = None
    _walletdb_loop = None

    def __init__(self, contract_hash, wallet_path, wallet_pass):
        super(LootMarketsSmartContract, self).__init__()
        self.daemon = True

        self.contract_hash = contract_hash
        self.wallet_path = wallet_path
        self.wallet_pass = wallet_pass

        self.smart_contract = SmartContract(contract_hash)
        self.invoke_queue = Queue()

        # Setup redis cache.
        self.redis_cache = redis.StrictRedis(host='localhost', port=6379, db=0)

        self.calling_transaction = None
        self.tx_in_progress = None
        self.wallet = None

        settings.set_log_smart_contract_events(False)

        # Setup handler for smart contract Runtime.Notify event.
        # Here we listen to all notify events.
        @self.smart_contract.on_notify
        def sc_notify(event):
            """ This method catches Runtime.Notify calls, and updates the relevant cache. """

            # Log the received smart contract event.
            logger.info("- SmartContract Event: %s", str(event))
            event_name = event.event_payload[0].decode("utf-8")

            # ==== General Events ====
            # Smart contract events that are not specific to a marketplace.

            # Event: balance_of
            if event_name == "balance_of":
                # Convert the given script hash to an address.
                script_hash = event.event_payload[1]
                sh = UInt160.UInt160(data=script_hash)
                address = Crypto.ToAddress(sh)
                balance = int.from_bytes(event.event_payload[2], 'little')
                # Save the balance to the cache.
                logger.info("- Balance of %s updated to %s LOOT", address, balance)
                self.redis_cache.set("balance:%s" % address, int(balance))
                return

            # Event: get_marketplace_owner
            if event_name == "get_marketplace_owner":
                marketplace = event.event_payload[1].decode("utf-8")
                script_hash = event.event_payload[2]
                sh = UInt160.UInt160(data=script_hash)
                address = Crypto.ToAddress(sh)
                logger.info("- Owner of %s: %s", marketplace, address)
                self.redis_cache.set("owner:%s" % marketplace, address)
                return

            # ==== Marketplace Events ====
            # Events that are specific to a marketplace.

            # Get the name of the marketplace, if it is none this is not a marketplace operation, return.
            marketplace = event.event_payload[1]
            if marketplace is not None:
                marketplace = marketplace.decode("utf-8")
            else:
                return

            # Ignore smart contract events that are not on our marketplace being used.
            if marketplace != self.marketplace:
                return

            # Event: get_inventory
            if event_name == "get_inventory":
                # Convert the script hash to an address.
                script_hash = event.event_payload[2]
                sh = UInt160.UInt160(data=script_hash)
                address = Crypto.ToAddress(sh)

                # After being converted from a byte to an int, append each element to the list.
                inventory = []
                for i in event.event_payload[3]:
                    item_id = int.from_bytes(i, 'little')
                    inventory.append(item_id)

                # Update the inventory in the redis cache.
                logger.info("- Setting inventory of %s to %s", address, inventory)
                self.redis_cache.set("inventory:%s" % address, inventory)
                self.redis_cache.set("inventoryUpdatedAt:%s" % address, int(time.time()))

            # Event: get_all_offers
            if event_name == "get_all_offers":
                retrieved_offers = event.event_payload[2]
                # Decode all the offers given in the payload.
                offers = []
                for i in retrieved_offers:
                    # Offer is received like 'offer\x03' so we convert to 'offer3'.
                    # We don't want to show the cached offers to the players.
                    i = i.decode("utf-8")
                    if i not in self.cached_offers:
                        s = ord(i.split('offer')[1])
                        offer_id = 'offer' + str(s)
                        offers.append(offer_id)

                # Log the information and save to the cache.
                logger.info("-Setting offers in marketplace: %s", offers)
                self.redis_cache.set("offers", offers)
                self.redis_cache.set("timeOffersUpdated", str(datetime.now()))

            # Event: get_offer
            if event_name == "get_offer":
                print("Event: get_offer")
                # Get all the relevant information about the offer.
                offer = event.event_payload[2]
                address = offer[0]
                offer_id_encoded = offer[1]

                # If the offer is empty, return.
                if not offer:
                    return

                # We receive the offer index sent from contract in format e.g. "offer\x03", convert to "offer3".
                index = ord(offer_id_encoded.decode().split('offer')[1])
                offer_id = 'offer' + str(index)

                # Decode the bytes into integers.
                item_id = int.from_bytes(offer[2], 'little')
                price = int.from_bytes(offer[3], 'little')

                # Convert the script hash to an address.
                script_hash = address
                sh = UInt160.UInt160(data=script_hash)
                address = Crypto.ToAddress(sh)

                # Put the offer information in a list and save it to the redis cache with the offer id as the key.
                offer_information = [address, offer_id, item_id, price]
                logger.info("-Setting offer:%s to %s", offer_id, offer_information)
                self.redis_cache.set(offer_id, offer_information)

            # Event: Market/Item operation
            # The game/operator must know if these operations were successfully completed within the smart contract.
            # All of these notify events are sent in the same format.
            if event_name in ("cancel_offer", "buy_offer", "put_offer", "give_items", "remove_item"):
                # Convert the script hash to address.
                script_hash = event.event_payload[2]
                sh = UInt160.UInt160(data=script_hash)
                address = Crypto.ToAddress(sh)
                # Check if the operation was successfully completed within the smart contract.
                operation_successful = event.event_payload[3]
                # Save the address, and result to the cache with the event_name used as a key.
                self.redis_cache.set(event_name+"%s" % address, operation_successful)
                logger.info("-"+event_name+" of address %s was completed: %s", address, operation_successful)

    def add_invoke(self, operation_name, transaction_key, args):
        """
        Add a smart contract operation to the queue.

        :param operation_name:str The name of the operation to invoke.
        :param transaction_key:str The transaction key to associate with the transaction of the invoke.
        :param args:list The arguments to pass to the smart contract operation.
        """
        self.calling_transaction = True

        # By the LootMarkets smart contract convention, the marketplace name should be the
        # first element in the list of args for marketplace operations.
        args.insert(0, self.marketplace)

        logger.info("SmartContractInvokeQueue: add_invoke %s %s" % (operation_name, str(args)))
        logger.info("- The queue size is : %s", self.invoke_queue.qsize())
        self.invoke_queue.put((operation_name, transaction_key, args))

    def run(self):
        """ The smart contract invocation queue. """
        while True:
            task = self.invoke_queue.get()
            logger.info("SmartContractInvokeQueue Task: %s", str(task))
            operation_name,transaction_key, args = task
            logger.info("- operation_name: %s, args: %s", operation_name, task)
            logger.info("- queue size: %s", self.invoke_queue.qsize())

            try:
                self.invoke_operation(operation_name, transaction_key, *args)
            except Exception as e:
                logger.exception(e)

                # Wait a few seconds.
                logger.info("Waiting 10 seconds...")
                time.sleep(10)

                # Re-add the task to the queue.
                logger.info("Re-adding the task to the queue....")
                self.invoke_queue.put(task)

            finally:
                # Always mark task as done, because even on error it was done and re-added
                self.invoke_queue.task_done()

    def open_wallet(self):
        """ Open a wallet. Needed for invoking contract operations. """
        if self.wallet is not None:
            return
        self.wallet = UserWallet.Open(self.wallet_path, self.wallet_pass)
        self._walletdb_loop = task.LoopingCall(self.wallet.ProcessBlocks)
        self._walletdb_loop.start(1)

    def close_wallet(self):
        """ Close the currently opened wallet. """
        if self.wallet is None:
            return
        self._walletdb_loop.stop()
        self._walletdb_loop = None
        self.wallet = None

    def wallet_has_gas(self):
        """ Check if the wallet has gas available. """
        # Make sure no tx is in progress and we have GAS.
        if self.wallet is None:
            self.open_wallet()
        synced_balances = self.wallet.GetSyncedBalances()
        for balance in synced_balances:
            asset, amount = balance
            logger.info("- balance %s: %s", asset, amount)
            if asset == "NEOGas" and amount > 0:
                return True

        return False

    def claim_gas(self):
        """ Claim gas from the wallet associated with the API. """
        if self.wallet is None:
            self.open_wallet()
        ClaimGas(self.wallet)
        self.close_wallet()

    def _wait_for_tx(self,tx, max_seconds=300):
        """ Wait for the transaction to show up on the blockchain. """
        sec_passed = 0
        while sec_passed < max_seconds:
            _tx, height = Blockchain.Default().GetTransaction(tx.Hash.ToString())
            if height > -1:
                return True
            # logger.info("Waiting for tx {} to show up on blockchain...".format(tx.Hash.ToString()))
            time.sleep(5)
            sec_passed += 5

        logger.error("Transaction was relayed but never accepted by consensus node.")
        return False

    def search_tx(self,transaction_key):
        """
        Search for a transaction on the blockchain and the result of the operation.

        :param: transaction_key:str A key associated with a transaction which was returned when
        invoking a smart contract operation from the API.
        """
        # Get the tx with the given transaction_key.
        tx = self.redis_cache.get(transaction_key)

        # If nothing is saved in the cache, return.
        if not tx:
            return

        # Try find the transaction on the blockchain.
        _tx, height = Blockchain.Default().GetTransaction(tx.decode("utf-8"))

        # If we find a tx, save true to the redis cache, else set false.
        if _tx:
            self.redis_cache.set("tx%s" % transaction_key, True)
        else:
            self.redis_cache.set("tx%s" % transaction_key, False)

    def test_invoke(self,transaction_type,operation_name,*args):
        """
        Test invoke a smart contract operation. We catch the Notify events of the contract for instant query.

        :param transaction_type:str The type of smart contract operation we are test invoking.
        :param operation_name:str The name of the operation we are test invoking.
        :param args:list The arguments to pass to the smart contract operation.
        """
        if self.wallet is None:
            self.open_wallet()

        # If we get a marketplace specific operation, we need to add the marketplace
        # name in front of the argument list as hence the LootMarkets smart contract convention.
        if transaction_type == "market":
            l = list(args)
            l.insert(0,self.marketplace)
            _args = [self.contract_hash, operation_name, str(l)]

        # If we get a non-marketplace specific operation, we do not need to add the marketplace
        # name in front of the argument list.
        if transaction_type == "general":
            _args = [self.contract_hash, operation_name, str(list(args))]

        # Method of dealing with double backslashes being duplicated when sending.
        if transaction_type == "offer":
            # This transaction type will only be with an address or offer at the front.
            if "offer" in str(args[0]):
                offer_id = str(args[0])
            else:
                offer_id = str(args[1])
            l = str([self.marketplace, offer_id])
            list_to_add = l.replace("\\", '', 1)

            # If we were passed in an address, put that in front, else put just the offer id.
            if len(args) == 1:
                _args = [self.contract_hash, operation_name, list_to_add]
            else:
                address = str(args[0])
                _args = [self.contract_hash, operation_name, address, list_to_add]

        logger.info("TestInvokeContract args: %s", _args)
        tx, fee, results, num_ops = TestInvokeContract(self.wallet, _args)
        if not tx:
            logger.info("TestInvokeContract failed: no tx was found!")
            self.close_wallet()
            return

        # If we found the tx,the result is a success, and the operation
        # is a buy or cancel, we should cache it.
        if operation_name in ["buy_offer","cancel_offer"]:
            # Offers are concatenated in the smart contract for specific markets.
            offer_id = self.marketplace+offer_id
            self.cached_offers.append(offer_id)

    def invoke_operation(self, operation_name,transaction_key, *args):
        """
        Directly invoke a smart contract operation.

        :param operation_name:str The name of the smart contract operation to invoke.
        :param transaction_key:str The transaction key to associate with the transaction of the invoke.
        :param args:list The arguments to pass to the smart contract operation.
        """
        logger.info("invoke_operation: operation_name=%s, args=%s", operation_name, args)
        logger.info("Block %s / %s" % (str(Blockchain.Default().Height), str(Blockchain.Default().HeaderHeight)))

        self.open_wallet()

        if not self.wallet:
            raise Exception("Open a wallet before invoking a smart contract operation.")

        if self.tx_in_progress:
            raise Exception("Transaction already in progress (%s)" % self.tx_in_progress.Hash.ToString())

        logger.info("making sure wallet is synced...")
        time.sleep(10)

        # Wait until wallet is synced:
        while True:
            if not self.wallet:
                self.open_wallet()
            percent_synced = int(100 * self.wallet._current_height / Blockchain.Default().Height)
            if percent_synced > 99:
                break
            logger.info("waiting for wallet sync... height: %s. percent synced: %s" % (self.wallet._current_height, percent_synced))
            time.sleep(5)

        time.sleep(3)
        logger.info("wallet synced. checking if gas is available...")

        # If the wallet has no GAS, rebuild the wallet.
        if not self.wallet_has_gas():
            logger.error("Oh now, wallet has no gas! Trying to rebuild the wallet...")
            self.wallet.Rebuild()

            # Wait until rebuild is complete.
            while not len(self.wallet.GetSyncedBalances()):
                 percent_synced = int(100 * self.wallet._current_height / Blockchain.Default().Height)
                 logger.info("rebuilding wallet... height: %s. percent synced: %s" % (self.wallet._current_height, percent_synced))
                 time.sleep(10)

            logger.info(self.wallet.GetSyncedBalances())
            logger.info("Wallet rebuild complete. waiting 10 sec and trying again...")
            time.sleep(10)

            raise Exception("Wallet has no gas.")

        # The offer must be sent to contract exactly like e.g. "offer\x03" slashes are duplicated in the offer
        # strings when sent through the API, we remove the duplication.
        s = str(list(args))
        if "offer" in s:
            s = s.replace("\\",'',1)
            _args = [self.contract_hash, operation_name, s]
        else:
            _args = [self.contract_hash, operation_name, str(list(args))]

        logger.info("TestInvokeContract args: %s", _args)
        tx, fee, results, num_ops = TestInvokeContract(self.wallet, _args)

        if not tx:
            raise Exception("TestInvokeContract failed")

        # Store the transaction in redis.
        logger.info("TestInvokeContract done, calling InvokeContract now...")
        sent_tx = InvokeContract(self.wallet, tx, fee)

        if sent_tx:

            # Save the sent transaction in the redis cache.
            self.redis_cache.set(transaction_key,sent_tx.Hash.ToString())

            logger.info("InvokeContract success, transaction underway: %s" % sent_tx.Hash.ToString())
            self.tx_in_progress = sent_tx

            found = self._wait_for_tx(sent_tx)
            if found:
                logger.info("✅ Transaction found!")
            else:
                logger.error("=== TX not found!")

            # If this operation is buy or cancel, remove the last element
            # from the cached offers, the operations are ordered in the queue so we may do this.
            if operation_name in ["buy_offer","cancel_offer"]:
                del self.cached_offers[len(self.cached_offers)-1]

            self.close_wallet()

            # time.sleep(100)
            self.tx_in_progress = None
            logger.info("InvokeContract done, tx_in_progress freed.")

        else:
            raise Exception("InvokeContract failed")






