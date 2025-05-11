import os
from typing import List, Dict


def save_toc_and_course_content(course_content: List[Dict]):
    directory = "course-data"
    if not os.path.exists(directory):
        os.makedirs(directory)
    
    if os.path.isfile('course-data/course_content.txt'):
        os.remove('course-data/course_content.txt')
    
    with open('course-data/course_content.txt', 'a') as file:
        file.write("# Table of contents\n")
        for i, module in enumerate(course_content, 1):
            file.write(f'{i}. **{module['title']}**\n')
        file.write('\n')
        for module in course_content:
            file.write('\n# ' + module['title'])
            file.write('\n\n' + module['content'])


def save_summary(chunks_summaries: List[str]):
    directory = "course-data"
    if not os.path.exists(directory):
        os.makedirs(directory)
    
    with open('course-data/summarized-doc.txt', 'w') as file:
        file.write(''.join(chunks_summaries))
