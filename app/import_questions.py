"""Bounded CSV/XLSX parsing on the backend. Invalid answers are never guessed."""
import csv
import io
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from openpyxl import load_workbook
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app.resources import QuestionInput
from app.security import admin

router = APIRouter(prefix='/api/v1/admin/questions', tags=['question imports'])
LIMIT = 1000


def parse_questions(blob: bytes, filename: str, subject: str, year: str) -> list[dict]:
    extension = Path(filename).suffix.lower()
    workbook = None
    try:
        if extension == '.csv':
            reader = csv.DictReader(io.StringIO(blob.decode('utf-8-sig')))
        elif extension == '.xlsx':
            with ZipFile(io.BytesIO(blob)) as archive:
                if sum(item.file_size for item in archive.infolist()) > 50 * 1024 * 1024:
                    raise ValueError('Spreadsheet expands beyond the size limit')
            workbook = load_workbook(io.BytesIO(blob), read_only=True, data_only=True, keep_links=False)
            sheet = workbook.worksheets[0]
            values = sheet.iter_rows(values_only=True)
            headers = next(values, ())
            reader = (dict(zip(headers, row)) for row in values)
        else:
            raise ValueError('Use a CSV or XLSX file')
        output = []
        for number, row in enumerate(reader, 2):
            if number > LIMIT + 1:
                raise ValueError('Upload at most 1,000 rows at a time')
            if not any(value is not None and str(value).strip() for value in row.values()):
                continue
            row = {str(key).strip().lower(): str(value).strip() if value is not None else '' for key, value in row.items()}
            options = [row.get(letter, '') for letter in 'abcd']
            answer = row.get('answer', '')
            if answer.upper() in ('A', 'B', 'C', 'D'):
                index = ord(answer.upper()) - ord('A')
            elif answer in options and len(set(options)) == 4:
                index = options.index(answer)
            else:
                raise ValueError(f'Row {number}: Answer must identify one of the four options')
            try:
                question = QuestionInput(subject_id=subject, year=year, text=row.get('question', ''),
                                         options=options, correct_option=index,
                                         explanation=row.get('explanation', ''), topic=row.get('topic') or None)
            except ValidationError:
                raise ValueError(f'Row {number}: Provide a question and four nonempty options') from None
            output.append(question.model_dump())
        if not output:
            raise ValueError('No questions found in the file')
        return output
    except (ValueError, UnicodeError, BadZipFile, OSError, KeyError, IndexError) as error:
        raise HTTPException(422, str(error) if isinstance(error, ValueError) else 'Invalid spreadsheet') from None
    finally:
        if workbook:
            workbook.close()


@router.post('/import-preview', dependencies=[Depends(admin)])
async def import_preview(file: UploadFile = File(...), subject_id: str = Form(...), year: str = Form(...)):
    try:
        blob = await file.read(10 * 1024 * 1024 + 1)
        if len(blob) > 10 * 1024 * 1024:
            raise HTTPException(413, 'Import exceeds 10 MB')
        return await run_in_threadpool(parse_questions, blob, file.filename or '', subject_id, year)
    finally:
        await file.close()
