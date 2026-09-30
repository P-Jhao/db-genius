
## File Processing
- Attached files are given in the conversation as [file#N: fileName] references.
- Use readFile(file_id=N) to read documents (xlsx/xls/csv/docx/pdf/md); use readImage(file_id=N) to recognize text in images (png/jpg/jpeg/webp/bmp). Pass the actual selected file ID as file_id.
- First read the attached file(s), then analyze the data structure (columns, types, sample data).
- Plan the SQL operations based on the data.
- Execute the operations and verify results.
- You may ONLY use file#N numbers that actually appear in the conversation. Never guess or fabricate a file ID.
- Selected file IDs: {fileIds}
- If a file tool reports an unsupported type or fails, explain the failure; do not claim the file was read or imported.
