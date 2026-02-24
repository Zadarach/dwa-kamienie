from .items.items import Items
from .requester import requester


class Vinted:
    """
    Główny klient API Vinted.
    Umożliwia wyszukiwanie przedmiotów na podstawie URL filtrów.
    """

    def __init__(self, proxy=None):
        if proxy:
            requester.session.proxies.update(proxy)
        self.items = Items()
