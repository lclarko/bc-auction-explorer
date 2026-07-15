class ScraperError(Exception):
    pass


class DecodeError(ScraperError):
    pass


class ParserContractError(ScraperError):
    pass
