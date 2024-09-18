import os
import re
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

def search_keywords_in_file(file_path, keywords, case_sensitive, use_regex):
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as file:
            content = file.read()
            if not case_sensitive:
                content = content.lower()
            
            for keyword in keywords:
                if use_regex:
                    if re.search(keyword, content, flags=0 if case_sensitive else re.IGNORECASE):
                        return file_path, keyword
                else:
                    if not case_sensitive:
                        keyword = keyword.lower()
                    if keyword in content:
                        return file_path, keyword
    except Exception as e:
        print(f"Error processing file {file_path}: {str(e)}")
    return None

def should_process_file(file_path, file_extensions, exclusions):
    if exclusions:
        for exclusion in exclusions:
            if exclusion in file_path:
                return False
    return file_extensions is None or any(file_path.endswith(ext) for ext in file_extensions)

def search_keywords_in_folder(folder_path, keywords, file_extensions, exclusions, case_sensitive, use_regex):
    files_with_keywords = []
    all_files = []
    for root, dirs, files in os.walk(folder_path):
        if exclusions:
            dirs[:] = [d for d in dirs if all(excl not in os.path.join(root, d) for excl in exclusions)]
        for file in files:
            file_path = os.path.join(root, file)
            if should_process_file(file_path, file_extensions, exclusions):
                all_files.append(file_path)

    with ThreadPoolExecutor() as executor:
        futures = [executor.submit(search_keywords_in_file, file_path, keywords, case_sensitive, use_regex) 
                   for file_path in all_files]
        
        for future in tqdm(as_completed(futures), total=len(all_files), desc="Searching files"):
            result = future.result()
            if result:
                files_with_keywords.append(result)
    
    return files_with_keywords

def main():
    parser = argparse.ArgumentParser(description="Advanced keyword search in files within a folder.")
    parser.add_argument("folder_path", help="Path to the folder to search in")
    parser.add_argument("-k", "--keywords", nargs="+", required=True, help="Keywords or regex patterns to search for")
    parser.add_argument("-e", "--extensions", nargs="*", help="File extensions to search (if not specified, searches all files)")
    parser.add_argument("-x", "--exclude", nargs="*", help="Exclude directories or file types")
    parser.add_argument("-c", "--case-sensitive", action="store_true", help="Enable case-sensitive search")
    parser.add_argument("-r", "--regex", action="store_true", help="Use regular expressions for search")
    parser.add_argument("-o", "--output", help="Output file to store results")
    args = parser.parse_args()

    file_extensions = [ext if ext.startswith('.') else f'.{ext}' for ext in args.extensions] if args.extensions else None

    files_found = search_keywords_in_folder(args.folder_path, args.keywords, file_extensions, args.exclude, args.case_sensitive, args.regex)

    output = f"\nTotal files containing keywords: {len(files_found)}\n"
    if file_extensions:
        output += f"Extensions searched: {', '.join(file_extensions)}\n"
    else:
        output += "Searched all file types\n"
    
    if args.exclude:
        output += f"Excluded: {', '.join(args.exclude)}\n"
    
    output += "\nFiles containing keywords:\n"
    for file_path, keyword in files_found:
        output += f"Keyword '{keyword}' found in file: {file_path}\n"

    print(output)

    if args.output:
        with open(args.output, 'w') as f:
            f.write(output)
        print(f"Results written to {args.output}")

if __name__ == "__main__":
    main()