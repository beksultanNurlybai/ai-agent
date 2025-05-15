import os
from typing import List, Dict


def save_course_content(course_content: List[Dict], course_summary: str, course: str):
    directory = "course-data"
    if not os.path.exists(directory):
        os.makedirs(directory)
    
    if os.path.isfile('course-data/course_content.txt'):
        os.remove('course-data/course_content.txt')
    
    with open('course-data/course_content.txt', 'a') as file:
        file.write(f'# {course}\n{course_summary}\n\n')
        file.write('# Table of contents\n')
        for i, module in enumerate(course_content, 1):
            file.write(f'{i}. **{module['title']}**\n')
        file.write('\n')
        for module in course_content:
            file.write('\n# ' + module['title'])
            file.write('\n\n' + module['content'])
