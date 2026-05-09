INDEX_PAGE_SIZE = 4096

def set_index_page_size(size: int) -> None:
    global INDEX_PAGE_SIZE
    INDEX_PAGE_SIZE = int(size)

def get_index_page_size() -> int:
    return INDEX_PAGE_SIZE
