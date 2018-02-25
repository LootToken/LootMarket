"""
=====================================================================================

===== Loot-Market =====

MIT License

Copyright 2018 LootToken Inc.

This smart contract creates a standard for games to integrate a storage system
for items on the NEO blockchain as "digital assets". This enables the construction of marketplaces,
a way for players to trade these "digital assets" for the NEP-5 asset LOOT tied to
a fiat value. These marketplaces can be registered for use in their game, where they are granted
exclusive permissions to invoke the operations on their named marketplace.
The system is immutable, secure, fee-less, and without third party.

Author: Christopher Luke Poli - @poli
Email: aus.poli1@gmail.com

======================================================================================
"""

from boa.code.builtins import concat, list, range, take, substr
from boa.blockchain.vm.System.ExecutionEngine import GetScriptContainer, GetExecutingScriptHash
from boa.blockchain.vm.Neo.Transaction import Transaction, GetReferences, GetOutputs
from boa.blockchain.vm.Neo.Output import GetValue, GetAssetId, GetScriptHash
from boa.blockchain.vm.Neo.Runtime import GetTrigger, CheckWitness, Notify
from boa.blockchain.vm.Neo.TriggerType import Application, Verification
from boa.blockchain.vm.Neo.Storage import Get, Put, Delete, GetContext
from boa.blockchain.vm.Neo.Transaction import GetUnspentCoins
from boa.blockchain.vm.Neo.Action import RegisterAction
from boa.blockchain.vm.Neo.Blockchain import GetHeight


# region Variables

# Wallet hash of the owner.
contract_owner = b'\xb2\x97\xed\x8c\x0b-$M?\xde\xc8j\xd1 \xd7\x8d\xef\xa3\x9c\xdf'

# Storage keys - used to get something from storage.
inventory_key = b'Inventory'                       # The inventory of an address.
item_key = b'item'                                 # The details of an item.
marketplace_key = b'marketplace'                   # The owner of a marketplace
offers_key = b'Offers'                             # All the offers available on a marketplace.
current_offer_index_key = b'current_offer_index'   # The current offer index of a marketplace.
token_deployed = b'deployed'                       # Has the token been deployed.
in_circulation_key = b'in_circulation'             # The LOOT in circulation.
kyc_key = b'kyc_okay'                              # Is an address KYC registered.
limited_round_key = b'r1'                          # The amount of tokens an address has exchanged in the first round.


# ICO variables
name = "LootToken"                     # The name of the token.
symbol = "LOOT"                        # The symbol of our token.
decimals = 8                           # The decimals of the token.
initial_amount_of_tokens = 50000000    # The token amount reserved for owners.
total_supply = 1000000000              # The total supply of the token.
tokens_per_neo = 10000                 # Receive 10 thousand tokens per NEO.
block_sale_start = 371613              # Which block to start the crowd-sale.
limited_round_end = 1000000            # Which block the limited round ends.
max_exchange_limited_round = 10000000  # The maximum tokens an address can exchange on the limited round.


# Events
OnTransfer = RegisterAction('transfer', 'from', 'to', 'amount')
OnRefund = RegisterAction('refund', 'to', 'amount')
OnInvalidKYCAddress = RegisterAction('invalid_registration','address')
OnKYCRegister = RegisterAction('kyc_registration','address')

# endregion


# region Structs

class Attachments:
    """ A container object for passing around information about attached NEO and GAS. """
    neo_attached = 0
    gas_attached = 0
    sender_addr = 0
    receiver_addr = 0
    neo_asset_id = b'\x9b|\xff\xda\xa6t\xbe\xae\x0f\x93\x0e\xbe`\x85\xaf\x90\x93\xe5\xfeV\xb3J\\"\x0c\xcd\xcfn\xfc3o\xc5'
    gas_asset_id = b'\xe7-(iy\xeel\xb1\xb7\xe6]\xfd\xdf\xb2\xe3\x84\x10\x0b\x8d\x14\x8ewX\xdeB\xe4\x16\x8bqy,`'


class Offer:
    """ A container object for storing the details of an offer. """
    address_owner = ""
    offer_id = 0
    item_id = 0
    price = 0


class Item:
    """ A container object used to store the custom attributes of an item. """
    item_id = 0
    item_type = ""
    item_rarity = ""
    item_damage = 0

# endregion


def Main(operation, args):
    """
    The entry point for the smart contract.

    :param operation: str The operation to invoke.
    :param args: list A list of arguments for the operation.
    :return:
        bytearray: The result of the operation.
    """

    print("LootMarkets: Version 1.0: CoZ testnet deployment")

    trigger = GetTrigger()

    if trigger == Application():

        # ========= Item Operations =========

        # Give items to an address on a marketplace.
        if operation == "give_items":
            marketplace = args[0]
            address = args[1]
            # Notify the API whether the items were given.
            operation_result = give_items(args)
            transaction_details = ["give_items", marketplace, address, operation_result]
            Notify(transaction_details)
            return operation_result

        # Remove an item from an address on a marketplace.
        if operation == "remove_item":
            if len(args) == 3:
                marketplace = args[0]
                address = args[1]
                item_id = args[2]
                # Notify the API whether the item was removed.
                operation_result = remove_item(marketplace, address, item_id)
                transaction_details = ["remove_item", marketplace, address, operation_result]
                Notify(transaction_details)
                return operation_result

        # Transfer an item from an address to an address on a marketplace.
        if operation == "transfer_item":
            if len(args) == 4:
                marketplace = args[0]
                address_from = args[1]
                address_to = args[2]
                item_id = args[3]
                # Notify the API with the details of the item transfer.
                operation_result = transfer_item(marketplace, address_from, address_to, item_id)
                transaction_details = ["transfer_item", marketplace, address_from, address_to, item_id, operation_result]
                Notify(transaction_details)
                return operation_result

        # Query the inventory of an address on a marketplace.
        if operation == "get_inventory":
            if len(args) == 2:
                marketplace = args[0]
                address = args[1]
                inventory_s = get_inventory(marketplace, address)
                inventory = deserialize_bytearray(inventory_s)
                # Notify the API with the details of the inventory.
                transaction_details = ["get_inventory", marketplace, address, inventory]
                Notify(transaction_details)
                return True

        """
        Ommited create item functionality due to not having a strong argument to store details of items on the 
        blockchain. Item details are best stored off chain by the registerer of the marketplace.
        This code has been left as an example.
        
        # Create a new item.
        if operation == "create_item":
            if len(args) == 5:
                marketplace = args[0]
                item_id = args[1]
                item_type = args[2]
                item_rarity = args[3]
                item_damage = args[4]
                # Notify the API whether the item was created.
                operation_result = create_item(marketplace, item_id, item_type, item_rarity, item_damage)
                transaction_details = ["create_item", marketplace, item_id, operation_result]
                Notify(transaction_details)
                return operation_result
                
        # Query the details of an item.
        if operation == "get_item":
            if len(args) == 2:
                marketplace = args[0]
                item_id = args[1]
                # Notify the API the details of the item.
                item_s = get_item(item_id)
                item = deserialize_bytearray(item_s)
                transaction_details = ["get_item", marketplace, item]
                Notify(transaction_details)
                return True
        """
        # ======== Marketplace Operations =========

        # Register a new marketplace on the blockchain.
        if operation == "register_marketplace":
            if len(args) == 2:
                marketplace = args[0]
                address = args[1]
                return register_marketplace(marketplace, address)

        # Query the owner address of a marketplace.
        if operation == "marketplace_owner":
            if len(args) == 1:
                marketplace = args[0]
                owner = marketplace_owner(marketplace)
                # Notify the API with the address of the marketplace owner.
                transaction_details = ["marketplace_owner", marketplace, owner]
                Notify(transaction_details)
                return True

        # Put an offer on a marketplace.
        if operation == "put_offer":
            if len(args) == 4:
                marketplace = args[0]
                address = args[1]
                item_id = args[2]
                price = args[3]
                # Notify the API if the offer was put.
                operation_result = put_offer(marketplace, address, item_id, price)
                transaction_details = ["put_offer", marketplace, address, operation_result]
                Notify(transaction_details)
                return operation_result

        # Buy an offer on a marketplace.
        if operation == "buy_offer":
            if len(args) == 3:
                marketplace = args[0]
                address_to = args[1]
                offer_id = args[2]
                # Notify the API if the offer was bought.
                operation_result = buy_offer(marketplace, address_to, offer_id)
                transaction_details = ["buy_offer", marketplace, address_to, operation_result]
                Notify(transaction_details)
                return operation_result

        # Cancel an offer on a marketplace.
        if operation == "cancel_offer":
            if len(args) == 3:
                marketplace = args[0]
                address = args[1]
                offer_id = args[2]
                # Notify the API if the offer was cancelled.
                operation_result = cancel_offer(marketplace, address, offer_id)
                transaction_details = ["cancel_offer", marketplace, address, operation_result]
                Notify(transaction_details)
                return operation_result

        # Query the details of an offer on a marketplace.
        if operation == "get_offer":
            if len(args) == 2:
                marketplace = args[0]
                offer_id = args[1]
                offer_s = get_offer(marketplace, offer_id)
                offer = deserialize_bytearray(offer_s)
                # Notify the API with the details of the offer.
                transaction_details = ["get_offer", marketplace, offer]
                Notify(transaction_details)
                return True

        # Query all the offer ids on a marketplace.
        if operation == "get_all_offers":
            if len(args) == 1:
                marketplace = args[0]
                offers_s = get_all_offers(marketplace)
                offers = deserialize_bytearray(offers_s)
                # Notify the API with the ids of the offers.
                transaction_details = ["get_all_offers", marketplace, offers]
                Notify(transaction_details)
                return True

        # ========= Crowdsale & NEP-5 Specific Operations ==========

        # Commands only the owner can invoke.
        if CheckWitness(contract_owner):

            # Register a list of addresses for KYC.
            if operation == "kyc_register":
                return kyc_register(args)

            # Deploy LOOT.
            if operation == "deploy_token":
                return deploy_token()

            # Transfer LOOT from an address, to another address.
            if operation == "transfer":
                if len(args) == 3:
                    address_from = args[0]
                    address_to = args[1]
                    amount = args[2]
                    return transfer_token(address_from, address_to, amount)

        # Check the KYC status of an address.
        if operation == "kyc_status":
            if len(args) == 1:
                address = args[0]
                return kyc_status(address)

        # Query the LOOT balance of an address.
        if operation == "balance_of":
            if len(args) == 1:
                address = args[0]
                balance = balance_of(address)
                # Notify the API with the LOOT balance of the address.
                transaction_details = ["balance_of", address, balance]
                Notify(transaction_details)
                return balance

        # Mint tokens during the crowdsale period.
        if operation == "mint_tokens":
            return mint_tokens()

        # Query the circulating supply of the token.
        if operation == "get_circulation":
            return get_circulation()

        # Query the name of the token.
        if operation == "get_name":
            return name

        # Query the symbol of the token.
        if operation == "get_symbol":
            return symbol

        # Query how many decimals the token has.
        if operation == "get_decimals":
            return decimals

        # Query the total supply of the token.
        if operation == "get_total_supply":
            return total_supply

    # Verification portion of the contract to determine whether the transfer
    # of system assets (NEO/Gas) involving this contracts address can proceed.
    if trigger == Verification():

        is_owner = CheckWitness(contract_owner)
        # If is the owner, proceed.
        if is_owner:
            return True
        return False

    return False


# region Inventory Methods

def give_items(args):
    """
    Give a number of items to an address on a marketplace.

    :param args:list A list containing the following:
            args[0]:str The marketplace being used.
            args[1]:str The address to give the items to.
            args[2:]:list A list of items to give the address.
    :return:
        bool: Whether the operation completed.
    """
    marketplace = args[0]
    address = args[1]

    # Check marketplace permissions.
    owner = marketplace_owner(marketplace)
    if not CheckWitness(owner):
        print("Operation Forbidden: Only the owner of this marketplace may invoke the operation - give_items")
        return False

    # Get the address's inventory from storage.
    inventory_s = get_inventory(marketplace, address)

    # If the inventory has no items, create a new list, else get the pre-existing list.
    if not inventory_s:
        inventory = []
    else:
        inventory = deserialize_bytearray(inventory_s)

    # This method does not work if this print statement is removed.
    # Excluding the marketplace and address, append all the items to the inventory.
    print("placeholder")
    for item in args:
        if item != marketplace and item != address:
            inventory.append(item)

    # Serialize and save the modified inventory back into storage.
    inventory_s = serialize_array(inventory)
    save_inventory(marketplace, address, inventory_s)

    return True


def remove_item(marketplace, address, item_id):
    """
    Remove an item from an address on a marketplace.

    :param marketplace:str The name of the marketplace to access.
    :param address:str The address to remove the item from.
    :param item_id:int The id of the item to remove from the address.
    :return:
        bool: Whether the item is removed.
    """

    # Check marketplace permissions.
    owner = marketplace_owner(marketplace)
    if not CheckWitness(owner):
        print("Operation Forbidden: Only the owner of this marketplace may invoke the operation - remove_item")
        return False

    # Get the address's inventory.
    inventory_s = get_inventory(marketplace, address)
    inventory = deserialize_bytearray(inventory_s)

    current_index = 0
    # TODO: Remove manually searching for the index once list method "indexOf" is added.
    for item in inventory:
        # If the player has the item, we can remove the item at the current index,
        # save the modified inventory to storage and return True.
        if item == item_id:
            inventory.remove(current_index)
            inventory_s = serialize_array(inventory)
            save_inventory(marketplace, address, inventory_s)
            return True
        current_index += 1
    return False


def transfer_item(marketplace, address_from, address_to, item_id):
    """
    Transfer an item from an address, to an address on a marketplace.

    :param marketplace:str The name of the marketplace to access.
    :param address_to:str The address receiving the item.
    :param address_from:str The address sending the item.
    :param item_id:int The id of the item being sent.
    :return:
        bool:Whether the transfer of the item was successful.
    """
    # Check marketplace permissions.
    owner = marketplace_owner(marketplace)
    if not CheckWitness(owner):
        print("Operation Forbidden: Only the owner of this marketplace may invoke the operation - transfer_item")
        return False

    # If the item is being transferred to the same address, don't waste gas and return True.
    if address_from == address_to:
        return True

    # If the removal of the item from the address sending is successful, give the item to the address receiving.
    if remove_item(marketplace, address_from, item_id):
        # Give the item to the address receiving and return True.
        args = [marketplace, address_to, item_id]
        give_items(args)
        return True

    return False


def create_item(marketplace, item_id, item_type, item_rarity, item_damage):
    """
    Create an item and register it on a marketplace.

    :param marketplace:str The name of the marketplace to access.
    :param item_id:int The id of the item to create.
    :param item_type:str An example attribute for an item.
    :param item_rarity:str An example attribute for an item.
    :param item_damage:str An example attribute for an item.
    :return:
        bool: Whether the item was created.
    """
    owner = marketplace_owner(marketplace)
    if not CheckWitness(owner):
        print("Operation Forbidden: Only the owner of this marketplace may invoke the operation - create_item")
        return False

    context = GetContext()

    # Concatenate a specific key to store it on a marketplace.
    item_marketplace_key = concat(item_key, marketplace)
    storage_key = concat(item_marketplace_key, item_id)

    # If the item already exists, return False.
    item_existing = Get(context, storage_key)
    if item_existing:
        print("An item with that id already exists!")
        return False

    # Create an item container object to hold attributes for the item.
    item = Item()
    # Pass in a unique id for the item.
    item.item_id = item_id
    # Set declared attributes for the item.
    item.item_type = item_type
    item.item_rarity = item_rarity
    item.item_damage = item_damage

    # Serialize the item into storage.
    item_s = serialize_array(item)
    Put(context, storage_key, item_s)

    return True


def get_item(marketplace, item_id):
    """
    Get the details of an item on a marketplace.
    
    :param marketplace:str The name of the marketplace to access.
    :param item_id:int The id of the item to get.
    :return:
        bytearray: A serialized item container object with the details of the item.
    """
    context = GetContext()

    # Concatenate a specific key to store on a unique marketplace.
    item_marketplace_key = concat(item_key, marketplace)
    storage_key = concat(item_marketplace_key, item_id)
    item_s = Get(context, storage_key)

    return item_s


def get_inventory(marketplace,address):
    """
    Get the items the address owns on a marketplace.

    :param marketplace:str The name of the marketplace to access.
    :param address:str The address of the inventory to get.
    :return:
        bytearray: A serialized list containing the items that the address owns.
    """
    context = GetContext()

    # Return the serialized inventory for the address.
    inventory_marketplace_key = concat(inventory_key, marketplace)
    storage_key = concat(inventory_marketplace_key, address)
    items_serialized = Get(context, storage_key)

    return items_serialized


def save_inventory(marketplace, address, inventory):
    """
    Helper method for inventory operations, saves a serialized list of items to storage.

    :param marketplace:str The name of the marketplace to access.
    :param address:str The address of the inventory to save.
    :param inventory:bytearray A serialized list containing the items an address owns.
    :return:
        bool: Whether the operation completed.
    """
    context = GetContext()

    # Concatenate the specific storage key, delete the old storage
    # and add the updated inventory into storage.
    inventory_marketplace_key = concat(inventory_key, marketplace)
    storage_key = concat(inventory_marketplace_key, address)
    Delete(context, storage_key)
    Put(context, storage_key, inventory)

    return True


# endregion


# region Market Methods


def register_marketplace(marketplace, address):
    """
    Register a new marketplace on the blockchain.

    :param marketplace:str The name to register the new marketplace as.
    :param address:str The address of the owner who will have exclusive permissions for the created marketplace methods.
    :return:
        bool: Whether the marketplace was registered.
    """
    context = GetContext()

    # Only the owner of the contract can register a new marketplace.
    if not CheckWitness(contract_owner):
        print("Operation Forbidden: Only the owner of this contract may invoke the operation - register_marketplace")
        return False

    # If the marketplace has already been created, return False.
    if marketplace_owner(marketplace):
        print("A marketplace with this name already exists!")
        return False

    # Concatenate the owner key and save the address into storage.
    owner_key = concat(marketplace_key, marketplace)
    Put(context, owner_key, address)

    return True


def marketplace_owner(marketplace):
    """
    Get the address of the owner who has ownership over a specific marketplace.

    :param marketplace:str The name of the marketplace to check the owner.
    :return:
        bytearray: The address of the owner who owns the marketplace.
    """
    context = GetContext()

    # Concatenate the owner key and return the address from storage.
    owner_key = concat(marketplace_key, marketplace)
    owner = Get(context, owner_key)
    return owner


def put_offer(marketplace, address, item_id, price):
    """
    Put a new offer up on a marketplace.

    :return:
        bool: Whether the offer was put.
    """
    context = GetContext()

    # The price of the offer must be greater than 0.
    if price <= 0:
        return False

    # Check marketplace permissions.
    owner = marketplace_owner(marketplace)
    if not CheckWitness(owner):
        print("Operation Forbidden: Only the owner of this marketplace may invoke the operation - put_offer")
        return False

    # If the removal of the item from the address was successful, put the offer up.
    if remove_item(marketplace, address, item_id):

        # Concatenate the key to get the current index of the marketplace, then get the current offer index.
        marketplace_index_key = concat(current_offer_index_key, marketplace)
        index = Get(context, marketplace_index_key)

        # Concatenate the key to get all the offers on the marketplace.
        marketplace_offers_key = concat(offers_key,marketplace)

        # If the index has not been set yet we create it, else we create a new offer id with the current index.
        if not index:
            index = 1
            marketplace_offer_id = concat(marketplace, "offer\x01")
        else:
            # Create the offer id to put into storage.
            offer_id = concat("offer", index)
            # Concatenate the name of the marketplace and offer so we can access these offers on individual markets.
            marketplace_offer_id = concat(marketplace, offer_id)

        # Get the list of all offers that are currently up in the marketplace.
        all_offers_s = get_all_offers(marketplace)

        # If there are no offers in the storage, put the first element in a new list
        # else, append the offer id to the pre-existing list of offer ids.
        if not all_offers_s:
            all_offers = [marketplace_offer_id]
        else:
            all_offers = deserialize_bytearray(all_offers_s)
            all_offers.append(marketplace_offer_id)

        # Serialize the list of offers we have modified.
        all_offers_s = serialize_array(all_offers)
        # Create a new serialized offer ready to put into storage.
        offer = new_offer(address, marketplace_offer_id, item_id, price)

        # Put the list of all offers and the offer id into storage.
        Delete(context, marketplace_offers_key)
        Put(context, marketplace_offers_key, all_offers_s)
        Put(context, marketplace_offer_id, offer)

        # Can now increment the offer index for the marketplace and save it into storage.
        index += 1
        Delete(context, marketplace_index_key)
        Put(context, marketplace_index_key, index)

        return True

    return False


def new_offer(address_owner, offer_id, item_id, price):
    """
    Helper method used to create a new offer container object.

    :param address_owner:str The address of the owner who is putting this offer onto the marketplace.
    :param offer_id:int The id of the offer.
    :param item_id:int The id of the item the player wants to sell.
    :param price:int The price in LOOT the player wants to sell the item for.
    :return:
        bytearray: A serialized offer container object with the given details.
    """

    offer = Offer()
    offer.address_owner = address_owner
    offer.offer_id = offer_id
    offer.item_id = item_id
    offer.price = price

    offer_serialized = serialize_array(offer)
    return offer_serialized



def buy_offer(marketplace, address_from, offer_id):
    """
    Buy an offer that exists on a marketplace.

    :param marketplace:str The name of the marketplace to access.
    :param address_from:str The address attempting to buy an offer on a marketplace.
    :param offer_id:str The id of the offer to buy on a marketplace.
    :return:
        bool: Whether the offer was bought.
    """

    # Check marketplace permissions.
    owner = marketplace_owner(marketplace)
    if not CheckWitness(owner):
        print("Operation Forbidden: Only the owner of this marketplace may invoke the operation - buy_offer")
        return False

    # Deserialize the retrieved offer object from storage.
    offer_s = get_offer(marketplace, offer_id)
    offer = deserialize_bytearray(offer_s)

    # If there is no offer, return False.
    if not offer:
        return False

    # Get the details from the offer object.
    address_to = offer[0]
    offer_id = offer[1]
    item_id = offer[2]
    price = offer[3]

    # If the transfer of LOOT is successful, remove the item from the marketplace.
    if transfer_token(address_from, address_to, price):
        if remove_offer(marketplace, offer_id):
            args = [marketplace,address_from,item_id]
            give_items(args)
            return True

    return False


def cancel_offer(marketplace, address, offer_id):
    """
    Cancel an offer that exists on a marketplace.

    :param marketplace:str The name of the marketplace to access.
    :param address: The address cancelling the offer.
    :param offer_id: The id of the offer to cancel.
    :return:
        bool: Whether the offer was cancelled.
    """

    # Check marketplace permissions.
    owner = marketplace_owner(marketplace)
    if not CheckWitness(owner):
        print("Operation Forbidden: Only the owner of this marketplace may invoke the operation - cancel_offer")
        return False

    # Deserialize the retrieved offer object from storage.
    offer_s = get_offer(marketplace, offer_id)
    offer = deserialize_bytearray(offer_s)

    # If there is no offer in the storage, return False.
    if not offer:
        return False

    # Get the required details from the offer object.
    owner_address = offer[0]
    offer_id = offer[1]
    item_id = offer[2]

    # If the address cancelling is not the owner of the offer, return False.
    if not address == owner_address:
        return False

    # If the offer was successfully removed, give the item back to the owner.
    if remove_offer(marketplace, offer_id):
        args = [marketplace, address, item_id]
        if give_items(args):
            return True

    return False


def remove_offer(marketplace, offer_id):
    """
    Helper method to remove an offer that exists on a marketplace.

    :param marketplace:str The name of the marketplace to access.
    :param offer_id:int The id of the offer to remove.
    :return:
        bool: Whether the offer was removed.
    """
    context = GetContext()

    # Concatenate an offer key for the specified marketplace.
    marketplace_offers_key = concat(offers_key, marketplace)

    # Get all the available offers of a marketplace.
    offers_s = get_all_offers(marketplace)
    offers = deserialize_bytearray(offers_s)

    # Iterate through the offers, we must currently remove by index.
    # TODO: Remove manually searching for the index once list method "indexOf" is added.
    current_index = 0
    for offer in offers:
        # If the offer equals the offer_id remove at current_index.
        if offer == offer_id:
            offers.remove(current_index)
            # Replace the list of offers currently in storage with the modified list.
            offers_s = serialize_array(offers)
            Delete(context, marketplace_offers_key)
            Put(context, marketplace_offers_key, offers_s)
            # Delete the offer from the storage.
            Delete(context, offer_id)
            return True
        current_index += 1

    return False


def get_all_offers(marketplace):
    """
    Return the list of offers on a marketplace.

    :param marketplace:str The name of the marketplace to access.
    :return:
        bytearray: A serialized list containing all the offer ids on the marketplace.
    """
    context = GetContext()

    # Concatenate an offer key for the specified marketplace.
    marketplace_offers_key = concat(offers_key, marketplace)
    offers_serialized = Get(context, marketplace_offers_key)
    return offers_serialized


def get_offer(marketplace,offer_id):
    """
    Return the details of an offer on a marketplace.

    :param marketplace:str The name of the marketplace to access.
    :param offer_id: The id of the offer to get the details.
    :return:
        bytearray: A serialized offer container object containing the details of an offer.
    """
    context = GetContext()

    # Get the offer container object from storage and return it.
    marketplace_offer_key = concat(marketplace,offer_id)
    offer_s = Get(context, marketplace_offer_key)
    return offer_s

# endregion


# region NEP-5 Operations

def transfer_token(address_from, address_to, amount):
    """
    Transfer the specified amount of LOOT from an address, to an address.

    :param address_from:str The address sending the LOOT.
    :param address_to:str The address receiving the LOOT.
    :param amount:int The amount of LOOT being sent.
    :return:
        bool: Whether the transfer of LOOT was successful.
    """
    context = GetContext()

    # The amount being transferred must be > 0.
    if amount <= 0:
        return False

    # If the address is sending LOOT to itself, save on gas and return True.
    if address_from == address_to:
        return True

    # If the balance of the address sending the LOOT does not have enough, return False.
    balance_from = balance_of(address_from)
    if balance_from < amount:
        return False

    # Subtract the amount from the address sending the LOOT and save it to storage.
    balance_from -= amount
    Delete(context, address_from)
    Put(context, address_from, balance_from)

    # Add the LOOT to the address receiving the tokens and save it to storage.
    balance_to = balance_of(address_to)
    balance_to += amount
    Delete(context, address_to)
    Put(context, address_to, balance_to)

    # Dispatch the transfer event.
    # This event causes the "buy_offer" method to not work with the API.
    # OnTransfer(address_from, address_to, amount)

    return True


def balance_of(address):
    """
    Query the LOOT balance of an address.

    :param address:str The address to query the balance of.
    :return:
        int: The balance of the given address.
    """
    context = GetContext()
    balance = Get(context, address)
    return balance


# endregion


# region ICO operations

def deploy_token():
    """
    Initialize the token into storage.

    :return:
        bool: Whether the token was successfully initialized.
    """
    context = GetContext()
    if not Get(context, token_deployed):
        # Put a key in the storage to signal that the tokens have been initialized.
        Put(context, token_deployed, 1)
        # Give the owner wallet an initial amount and add the amount to the total token circulation.
        Put(context, contract_owner, initial_amount_of_tokens)
        add_to_circulation(initial_amount_of_tokens)
        return True

    return False


def mint_tokens():
    """
    Mint tokens during a crowdsale period.

    :return:
        bool: Whether tokens were successfully minted.
    """

    attachments = Attachments()
    context = GetContext()

    # If the token is not deployed yet, return.
    if not Get(context, token_deployed):
        print("Call deploy_token before minting..")
        return False

    tx = GetScriptContainer()  # type:Transaction
    references = tx.References
    attachments.receiver_addr = GetExecutingScriptHash()

    if len(references) > 0:

        reference = references[0]
        attachments.sender_addr = reference.ScriptHash

        sent_amount_neo = 0
        sent_amount_gas = 0

        for output in tx.Outputs:
            if output.ScriptHash == attachments.receiver_addr and output.AssetId == attachments.neo_asset_id:
                sent_amount_neo += output.Value

            if output.ScriptHash == attachments.receiver_addr and output.AssetId == attachments.gas_asset_id:
                sent_amount_gas += output.Value

        attachments.neo_attached = sent_amount_neo
        #attachments.gas_attached = sent_amount_gas

    # Accepting NEO for the sale.
    if attachments.neo_attached == 0:
        return False

    # The following looks up whether an address has been
    # registered with the contract for KYC regulations
    # this is not required for operation of the contract.
    if not kyc_status(attachments.sender_addr):
        return False

    # Calculate the amount requested.
    amount_requested = attachments.neo_attached * tokens_per_neo / 100000000

    # Check if we can exchange.
    can_exchange = calculate_can_exchange(amount_requested, attachments.sender_addr)

    if not can_exchange:
        return False

    # Lookup the current balance of the address.
    current_balance = Get(context, attachments.sender_addr)

    # Calculate the amount of tokens the attached neo will earn.
    exchanged_tokens = attachments.neo_attached * tokens_per_neo / 100000000

    # If using GAS instead of NEO use this.
    # exchanged_tokens += attachments.gas_attached * tokens_per_gas / 100000000

    # Add it to the exchanged tokens and put it into storage.
    new_total = exchanged_tokens + current_balance
    Put(context, attachments.sender_addr, new_total)

    # Update the circulation amount.
    add_to_circulation(exchanged_tokens)

    # Dispatch the transfer event.
    OnTransfer(attachments.receiver_addr, attachments.sender_addr, exchanged_tokens)

    return True


def calculate_can_exchange(amount: int, address):
    """
    Perform custom token exchange calculations here.

    :param amount:int Number of tokens to convert from asset to tokens.
    :param address:bytearray The address to mint the tokens to.
    :return:
        bool: Whether or not an address can exchange a specified amount.
    """
    height = GetHeight()

    context = GetContext()

    current_in_circulation = get_circulation()

    # Get the new amount of tokens.
    new_amount = current_in_circulation + amount

    if new_amount > total_supply:
        print("amount greater than total supply")
        return False

    print("trying to calculate height")
    if height < block_sale_start:
        print("sale not begun yet")
        return False

    # If we are in free round, any amount is acceptable.
    if height > limited_round_end:
        print("Free for all, accept as much as possible.")
        return True

    # Check amount in limited round.
    if amount <= max_exchange_limited_round:

        # Check if they have already exchanged in the limited round.
        r1key = concat(address, limited_round_key)

        has_exchanged = Get(context,r1key)

        # If not, then save the exchange for limited round.
        if not has_exchanged:
            Put(context,r1key, True)
            return True

        print("Already exchanged in limited round.")
        return False

    print("Too much for limited round.")

    return False


def kyc_register(args):
    """
    Register addresses for KYC.

    :param args: list A list of addresses to register for KYC
    :return:
        int: The number of addresses registered for KYC.
    """
    context = GetContext()
    ok_count = 0

    # Register all the addresses passed to the operation.
    for address in args:
        if len(address) == 20:
            kyc_storage_key = concat(kyc_key,address)
            Put(context,kyc_storage_key,True)

            OnKYCRegister(address)
            ok_count += 1

    return ok_count


def kyc_status(address):
    """
    Get the KYC status of an address.

    :param address: str An address to check if KYC registered.
    :return:
        bool: The kyc status of an address.
    """
    context = GetContext()
    kyc_storage_key = concat(kyc_key, address)
    return Get(context, kyc_storage_key)


def sale_amount_remaining():
    """
    The amount of tokens that are left for the sale.

    :return:
        int: The number of tokens left for sale.
    """
    context = GetContext()
    in_circulation = Get(context,in_circulation_key)
    available = total_supply - in_circulation
    return available

def get_circulation():
    """
    Returns the amount of tokens in circulation.

    :return:
        int: The total number of tokens that are in circulation.
    """
    context = GetContext()
    return Get(context,in_circulation_key)

def add_to_circulation(amount):
    """
    Adds an amount of tokens to add to the circulation.

    :param amount:int The amount of tokens to add to the total circulation.
    """
    context = GetContext()
    current_supply = Get(context,in_circulation_key)
    current_supply += amount
    Put(context,in_circulation_key,current_supply)
# endregion


# region Serialization Helpers

def deserialize_bytearray(data):
    """ Helper method to deserialize a byte array. """
    # If you remove this print statement it stops working.
    print("deserializing data...")

    # Get length of length.
    collection_length_length = substr(data, 0, 1)

    # Get length of collection.
    collection_len = substr(data, 1, collection_length_length)

    # Create a new collection.
    new_collection = list(length=collection_len)

    # Calculate offset.
    offset = 1 + collection_length_length

    # Trim the length data.
    newdata = data[offset:]

    for i in range(0, collection_len):

        # Get the data length length.
        itemlen_len = substr(newdata, 0, 1)

        # Get the length of the data.
        item_len = substr(newdata, 1, itemlen_len)

        start = 1 + itemlen_len
        end = start + item_len

        # Get the data.
        item = substr(newdata, start, item_len)

        # Store it in collection.
        new_collection[i] = item

        # Trim the data.
        newdata = newdata[end:]

    return new_collection


def serialize_array(items):
    """ Helper method to serialize an array such that it is able to be added to storage. """
    # Serialize the length of the list.
    itemlength = serialize_var_length_item(items)

    output = itemlength

    # Now go through and append all your stuff.
    for item in items:

        # Get the variable length of the item
        # to be serialized.
        itemlen = serialize_var_length_item(item)

        # Add that indicator.
        output = concat(output, itemlen)

        # Now add the item.
        output = concat(output, item)

    return output


def serialize_var_length_item(item):
    """ Helper method for serialize_array. """
    # Get the length of your stuff.
    stuff_len = len(item)

    # Now we need to know how many bytes the length of the array
    # will take to store.

    # This is one byte.
    if stuff_len <= 255:
        byte_len = b'\x01'
    # Two byte.
    elif stuff_len <= 65535:
        byte_len = b'\x02'
    # Hopefully 4 byte.
    else:
        byte_len = b'\x04'

    out = concat(byte_len, stuff_len)

    return out

# endregion