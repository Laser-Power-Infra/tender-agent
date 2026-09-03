from typing import TypedDict

class IngestionState(TypedDict, total=False):

    job_id:str
    document_id:str
    file_url:str

    #local document
    file_path:str

    #page tracking
    total_pages:int
    current_page:int

    # Current page processing
    page_markdown:str
    page_chunks:list[dict]

    # Processing
    status:str
    error:str|None    