import os
import glob
import re

routes_dir = '/Users/ef/Developer/artistv2/app/routes'
for filepath in glob.glob(os.path.join(routes_dir, '*.py')):
    with open(filepath, 'r') as f:
        content = f.read()
    
    # We want to find:
    # TemplateResponse(
    #     "filename.html",
    #     {
    
    # and replace with:
    # TemplateResponse(
    #     request=request, name="filename.html", context={
    
    # Regex: TemplateResponse\(\s*"([^"]+)",\s*\{
    new_content = re.sub(r'TemplateResponse\(\s*"([^"]+)",\s*\{', r'TemplateResponse(request=request, name="\1", context={', content)
    
    if new_content != content:
        with open(filepath, 'w') as f:
            f.write(new_content)
        print(f"Updated {filepath}")
