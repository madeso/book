#!/usr/bin/env python3
# Converts from the source markup format to HTML for the web version.

# todo(Gustav): add watcher (with auto refresh like hugo)
# todo(Gustav): copy source images to desination folder
# todo(Gustav): action to transform image to local folder
# todo(Gustav): action to modify markdown and download image
# todo(Gustav): action to modify downloaded image, change format and make black-white and dithering
# todo(Gustav): support epub

###################################################################################################
# Imports

import os
import typing
import argparse
import time
import json
import re
# import subprocess

# non-standard dependencies
import toml
import pystache
import markdown
import colorama


###################################################################################################
# Global setup

from colorama import Fore, Style
colorama.init(strip=True)


###################################################################################################
# Constants

# single file in book root
BOOK_FILE = '.book.json'

# a folder (or file) that is added to a book is considered a chapter
CHAPTER_FILE = '.chapter.json'

# a markdown that is automatically added to the folder first
# index or readme? readme.md goes nice with github browsing but index.html is another standard
CHAPTER_INDEX = 'index.md'


###################################################################################################
# JSON keys

CHAPTER_JSON_CHAPTERS = 'chapters'

BOOK_JSON_CHAPTER = 'chapter'
BOOK_JSON_COPYRIGHT = 'copyright'


###################################################################################################
###################################################################################################
###################################################################################################

FRONTMATTER_SEPERATOR_CHAR = '+'
FRONTMATTER_SEPERATOR_MIN_LENGTH = 3

def file_exist(file: str) -> bool:
    return os.path.isfile(file)

def folder_exist(file: str) -> bool:
    return os.path.isdir(file)


def read_file(path: str) -> str:
    # print('reading ' + path)
    with open(path, 'r', encoding='utf-8') as input_file:
        return input_file.read()


def read_frontmatter_file(path: str) -> typing.Tuple[typing.Any, str]:
    has_frontmatter = False
    first = []
    second = []
    with open(path, 'r', encoding='utf-8') as input_file:
        for line in input_file:
            if not has_frontmatter:
                s = line.strip()
                if len(s) >= FRONTMATTER_SEPERATOR_MIN_LENGTH and len(s) * FRONTMATTER_SEPERATOR_CHAR == s:
                    has_frontmatter = True
                else:
                    first.append(line)
            else:
                second.append(line)
        if has_frontmatter:
            frontmatter = {}
            try:
                frontmatter = toml.loads(''.join(first))
            except toml.decoder.TomlDecodeError as e:
                print(path, e)
            return (frontmatter, ''.join(second))
        else:
            return (None, ''.join(first))


def write_frontmatter_file(path: str, frontmatter:typing.Optional[typing.Any], content:str):
    print('Writing ' + path)
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as file_handle:
        if frontmatter is not None:
            print(toml.dumps(frontmatter).rstrip(), file=file_handle)
            print(FRONTMATTER_SEPERATOR_CHAR * FRONTMATTER_SEPERATOR_MIN_LENGTH, file=file_handle)
        print(content.rstrip(), file=file_handle)


def write_file(contents: str, path: str) -> str:
    print('Writing ' + path)
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as file_handle:
        print(contents, file=file_handle)


def run_markdown(contents: str):
    body = markdown.markdown(contents, extensions=['extra', 'def_list', 'codehilite'])
    body = body.replace('<aside markdown="1"', '<aside')
    return body


def change_extension(file: str, extension: str):
    base = os.path.splitext(file)[0]
    return base + "." + extension


def pretty(text):
    '''Use nicer HTML entities and special characters.'''
    text = text.replace(" -- ", "&#8202;&mdash;&#8202;")
    text = text.replace("à", "&agrave;")
    text = text.replace("ï", "&iuml;")
    text = text.replace("ø", "&oslash;")
    text = text.replace("æ", "&aelig;")
    return text


def is_all_up_to_date(input_files: typing.List[str], output: str) -> bool:
    sourcemod = 0
    for path in input_files:
        sourcemod = max(sourcemod, os.path.getmtime(path))

    destmod = 0
    if os.path.exists(output):
        destmod = max(destmod, os.path.getmtime(output))

    return sourcemod < destmod


def pystache_render(filename, template, data):
    renderer = pystache.renderer.Renderer(missing_tags='strict')
    try:
        return renderer.render(template, data)
    except pystache.context.KeyNotFoundError as e:
        print(filename, 'ERROR:', e)
        return ''

def parent_folder(folder: str) -> str:
    return os.path.abspath(os.path.join(folder, os.pardir))

def iterate_parent_folders(folder: str) -> typing.Iterable[str]:
    f = folder
    yield folder
    while True:
        child = parent_folder(f)
        if child != f:
            yield child
            f = child
        else:
            break


def book_path_in_folder(folder: str) -> str:
    return os.path.join(folder, BOOK_FILE)


def get_book_file(folder: str) -> typing.Optional[str]:
    book = book_path_in_folder(folder)
    if file_exist(book):
        return book
    return None


def find_book_file(folder: str) -> typing.Optional[str]:
    for f in iterate_parent_folders(folder):
        book = get_book_file(f)
        if book is not None:
            return book
    return None


def get_source_root():
    return os.path.dirname(__file__)


def get_template_root() -> str:
    return os.path.join(get_source_root(), 'templates')


def get_json(json_data: typing.Any, key: str, missing: str) -> str:
    if key in json_data:
        return json_data[key]
    else:
        return missing

def get_toml(toml_data: typing.Any, key: str, missing: str) -> str:
    if toml_data is None:
        return missing
    if key in toml_data:
        return toml_data[key]
    else:
        return missing

def copy_file_to_dist(dest, name):
    source = os.path.join(get_template_root(), name)
    content = read_file(source)
    write_file(content, dest)

def copy_default_html_files(style_css: str):
    copy_file_to_dist(style_css, 'style.css')


def make_relative(src: str, dst: str) -> str:
    source_folder = os.path.dirname(src)
    rel = os.path.relpath(dst, source_folder)
    return rel


# ![alt text](url)
re_image = re.compile(r'!\[[^\]]*\]\(([^)]+)\)')

def list_images_in_markdown(md: str) -> typing.Iterable[str]:
    for match in re_image.finditer(md):
        yield match.group(1)


###################################################################################################
###################################################################################################
###################################################################################################


class Templates:
    def __init__(self, folder: str, ext: str):
        self.index = read_file(os.path.join(folder, 'index.' + ext))
        self.template = read_file(os.path.join(folder, 'template.' + ext))


class Stat:
    def __init__(self):
        self.num_chapters = 0
        self.empty_chapters = 0
        self.total_words = 0

    def update(self, contents: str, name: str, is_chapter: bool):
        word_count = len(contents.split(None))
        if is_chapter:
            self.num_chapters += 1
            if word_count < 50:
                self.empty_chapters += 1
                print("    {}".format(name))
            elif word_count < 2000:
                self.empty_chapters += 1
                print("{}-{} {} ({} words)".format(Fore.YELLOW, Style.RESET_ALL, name, word_count))
            else:
                self.total_words += word_count
                print("{}✓{} {} ({} words)".format(Fore.GREEN, Style.RESET_ALL, name, word_count))
        else:
            # Section header chapters aren't counted like regular chapters.
            print("{}•{} {} ({} words)".format(Fore.GREEN, Style.RESET_ALL, name, word_count))

    def print_estimate(self):
        valid_chapters = self.num_chapters - self.empty_chapters
        average_word_count = self.total_words / valid_chapters if valid_chapters > 0 else 0
        estimated_word_count = self.total_words + (self.empty_chapters * average_word_count)
        percent_finished = self.total_words * 100 / estimated_word_count if estimated_word_count > 0 else 0

        print("{}/~{} words ({}%)".format(self.total_words, estimated_word_count, percent_finished))


class GlobalData:
    def __init__(self, the_copyright: str):
        # todo(Gustav): add support to write markdown in copyright (or just a footer)
        self.copyright = the_copyright


class GeneratedData:
    def __init__(self, glob: GlobalData, extension: str, book_title: str, root: str, toc: str, style_css: str, index_html: str):
        self.glob = glob
        self.extension = extension
        self.book_title = book_title
        self.root = root
        self.toc = toc
        self.style_css = style_css
        self.index_html = index_html


class GuessedData:
    def __init__(self, source: str):
        self.title = os.path.splitext(os.path.basename(source))[0]


TOML_GENERAL_TITLE = 'title'
TOML_INDEX_SIDEBAR = 'sidebar_file'
TOML_INDEX_AUTHOR = 'author_file'


class GeneralData:
    def __init__(self, frontmatter: typing.Any, guess: GuessedData):
        self.title = get_toml(frontmatter, TOML_GENERAL_TITLE, guess.title)

    def generate(self, frontmatter: typing.Any):
        frontmatter[TOML_GENERAL_TITLE] = self.title


class IndexData(GeneralData):
    def __init__(self,  frontmatter: typing.Any, guess: GuessedData):
        GeneralData.__init__(self, frontmatter, guess)
        self.sidebar_file = get_toml(frontmatter, TOML_INDEX_SIDEBAR, 'sidebar.md')
        self.author_file = get_toml(frontmatter, TOML_INDEX_AUTHOR, 'author.md')

    def generate(self, frontmatter: typing.Any):
        super().generate(frontmatter)
        frontmatter[TOML_INDEX_SIDEBAR] = self.sidebar_file
        frontmatter[TOML_INDEX_AUTHOR] = self.author_file


class ChapterData(GeneralData):
    def __init__(self,  frontmatter: typing.Any, guess: GuessedData):
        GeneralData.__init__(self, frontmatter, guess)

    def generate(self, frontmatter: typing.Any):
        super().generate(frontmatter)


class Page:
    def __init__(self, stat: Stat, chapter: str, source: str, target: str, is_chapter: bool, is_index: bool):
        self.source = source
        self.target = target
        self.frontmatter, self.content = read_frontmatter_file(self.source)
        self.guess = GuessedData(self.source)
        self.general = GeneralData(self.frontmatter, self.guess)
        self.is_chapter = is_chapter
        self.is_index = is_index
        self.chapter = chapter
        self.next_page = None
        self.prev_page = None
        # todo(Gustav): fix data
        self.parent = None
        self.children = []
        stat.update(self.content, chapter, is_chapter)

    @staticmethod
    def post_generation(pages: typing.List['Page']):
        last_page = None
        for page in pages:
            if last_page is not pages[0]:
                page.prev_page = last_page
            if last_page is not None:
                last_page.next_page = page
            last_page = page

    def generate_chapter_data(self, template: str, gen: GeneratedData) -> str:
        data = {}

        data['body'] = run_markdown(self.content)

        titles = [{"title": self.general.title}]
        section_headers = []

        p = self.parent
        while p is not None:
            if p.parent is not None:
                titles.append({"title": p.general.title})
                section_href = make_relative(self.target, p.target)
                section_headers.append({'title': p.general.title, 'href': section_href})
            p = p.parent
        section_headers.reverse()

        prev_page = '' if self.prev_page is None else make_relative(self.target, self.prev_page.target)
        next_page = '' if self.next_page is None else make_relative(self.target, self.next_page.target)

        data['title'] = self.general.title
        data['titles'] = titles
        data['section_headers'] = section_headers
        data['header'] = self.general.title
        data['prev'] = prev_page
        data['next'] = next_page
        data['index_html'] = make_relative(self.target, gen.index_html)
        data['style_css'] = make_relative(self.target, gen.style_css)
        data['book_title'] = gen.book_title
        data['copyright'] = gen.glob.copyright

        return pystache_render(self.source, template, data)

    def generate_index_data(self, template: str, gen: GeneratedData) -> str:
        data = {}

        info = IndexData(self.frontmatter, self.guess)

        data['index'] = run_markdown(self.content)

        sidebar_file = os.path.join(gen.root, info.sidebar_file)
        author_file = os.path.join(gen.root, info.author_file)

        data['book_title'] = gen.book_title
        data['copyright'] = gen.glob.copyright
        data['style_css'] = make_relative(self.target, gen.style_css)
        data['toc'] = gen.toc
        data['first_page'] = '' if self.next_page is None else make_relative(self.target, self.next_page.target)
        data['sidebar'] = run_markdown(read_file(sidebar_file))
        data['author'] = run_markdown(read_file(author_file))

        return pystache_render(self.source, template, data)

    def write(self, templates: Templates, gen: GeneratedData):
        generated = self.generate_index_data(templates.index, gen) if self.is_index else self.generate_chapter_data(templates.template, gen)
        write_file(generated, self.target)

    def generate_html_list(self, extension: str, indent: str, file: str):
        html = indent + '<li><a href="{}">{}</a>'.format(make_relative(file, self.target), self.general.title)
        # todo(Gustav): handle children in toc
        if len(self.children) > 0:
            html += '\n' + indent + '    <ul>\n'
            for c in self.children:
                html += c.generate_html_list(extension, indent + '    ', file) + '\n'
            html += indent + '    </ul>\n' + indent
        html += '</li>'
        return html


def update_frontmatter(chapter_path: str, create_data):
    frontmatter, content = read_frontmatter_file(chapter_path)
    write_chapter = False
    if frontmatter is None:
        write_chapter = True
        frontmatter = {}
        guess = GuessedData(chapter_path)
        chapter = create_data(frontmatter, guess)
        chapter.generate(frontmatter)
    if write_chapter:
        write_frontmatter_file(chapter_path, frontmatter, content)


def update_frontmatter_chapter(chapter_path: str):
    update_frontmatter(chapter_path, ChapterData)


def update_frontmatter_index(chapter_path: str):
    update_frontmatter(chapter_path, IndexData)


def create_page(stat: Stat, chapter: str, source_folder: str, target_folder: str, ext: str) -> Page:
    source = os.path.join(source_folder, chapter)
    target = os.path.join(target_folder, change_extension(chapter, ext) if file_exist(source) else chapter)
    book_index_file = os.path.join(os.path.dirname(find_book_file(source_folder)), CHAPTER_INDEX)
    is_index = source == book_index_file
    is_chapter = chapter == CHAPTER_INDEX
    return Page(stat, chapter, source, target, is_chapter, is_index)


class Chapter:
    def __init__(self, file_path: str):
        self.chapters = []
        self.file_path = file_path
        self.source_folder = os.path.dirname(file_path)

    def add_chapter(self, chap: str):
        self.chapters.append(chap)

    def from_json(self, data):
        self.chapters = data[CHAPTER_JSON_CHAPTERS]

    def to_json(self):
        data = {}
        data[CHAPTER_JSON_CHAPTERS] = self.chapters
        return data

    def save(self):
        write_file(json.dumps(self.to_json(), indent=4), self.file_path)

    @staticmethod
    def load(file_path: str) -> 'Chapter':
        book = Chapter(file_path)
        data = json.loads(read_file(file_path))
        book.from_json(data)
        return book

    def generate_pages(self, target_folder: str, ext: str, stat: Stat, pages: typing.List[Page]) -> Page:
        if not file_exist(os.path.join(self.source_folder, CHAPTER_INDEX)):
            print('error: missing chapter index')

        root_page = create_page(stat, CHAPTER_INDEX, self.source_folder, target_folder, ext)
        pages.append(root_page)

        book_index_file = os.path.join(os.path.dirname(find_book_file(self.source_folder)), CHAPTER_INDEX)

        for chapter in self.chapters:
            source = os.path.join(self.source_folder, chapter)
            target = os.path.join(target_folder, change_extension(chapter, ext) if file_exist(source) else chapter)
            if file_exist(source):
                is_index = source == book_index_file
                is_chapter = chapter == CHAPTER_INDEX
                child_page = Page(stat, chapter, source, target, is_chapter, is_index)
                pages.append(child_page)
                root_page.children.append(child_page)
                # if not root_page.is_index:
                child_page.parent = root_page
            elif folder_exist(source):
                section_file = os.path.join(source, CHAPTER_FILE)
                if file_exist(section_file):
                    section = Chapter.load(section_file)
                    child_page = section.generate_pages(target, ext, stat, pages)

                    root_page.children.append(child_page)
                    child_page.parent = root_page
                else:
                    print('ERROR: missing chapter file {}'.format(section_file))
            else:
                print('Neither file nor folder: {}'.format(source))

        return root_page

    def iterate_markdown_files(self) -> typing.Iterator[str]:
        yield os.path.join(self.source_folder, CHAPTER_INDEX)
        for chapter in self.chapters:
            source = os.path.join(self.source_folder, chapter)
            if file_exist(source):
                yield source
            elif folder_exist(source):
                section_file = os.path.join(source, CHAPTER_FILE)
                section = Chapter.load(section_file)
                for p in section.iterate_markdown_files():
                    yield p

    def update_frontmatters(self):
        index_file = os.path.join(self.source_folder, CHAPTER_INDEX)
        if file_exist(index_file):
            update_frontmatter_index(index_file)

        for chapter in self.chapters:
            path = os.path.join(self.source_folder, chapter)
            update_frontmatter_chapter(path)



def generate_toc(pages: typing.List[Page], extension: str, index_source: str, target: str) -> str:
    html = ''
    for page in pages:
        if page.source != index_source:
            html = html + page.generate_html_list(extension, '  ', target)
    return html


class Book(Chapter):
    def __init__(self, file_path: str):
        Chapter.__init__(self, file_path)
        self.the_copyright = ''

    def from_json(self, data):
        super().from_json(data[BOOK_JSON_CHAPTER])
        self.the_copyright = get_json(data, BOOK_JSON_COPYRIGHT, "")

    def to_json(self):
        data = {}
        data[BOOK_JSON_CHAPTER] = super().to_json()
        data[BOOK_JSON_COPYRIGHT] = self.the_copyright
        return data

    def generate_globals(self) -> GlobalData:
        return GlobalData(self.the_copyright)

    def save(self):
        write_file(json.dumps(self.to_json(), indent=4), self.file_path)

    @staticmethod
    def load(file_path: str) -> 'Book':
        book = Book(file_path)
        data = json.loads(read_file(file_path))
        book.from_json(data)
        return book

    def iterate_markdown_files(self) -> typing.Iterator[str]:
        chapter_path = os.path.join(self.source_folder, CHAPTER_INDEX)
        frontmatter, _ = read_frontmatter_file(chapter_path)
        if frontmatter is not None:
            data = IndexData(frontmatter, GuessedData(chapter_path))
            yield os.path.join(self.source_folder, data.sidebar_file)
            yield os.path.join(self.source_folder, data.author_file)
        for p in super().iterate_markdown_files():
            yield p


###################################################################################################
###################################################################################################
###################################################################################################


def handle_watch(_):
    while True:
        # check files
        time.sleep(0.3)


def handle_init(args):
    root = os.getcwd()
    path = find_book_file(root)
    if path is not None:
        if not args.update:
            print('Book is already defined in {}'.format(path))
            return
        book = Book.load(path)
        book.update_frontmatters()
    else:
        path = book_path_in_folder(root)
        book = Book(path)
        book.update_frontmatters()
        book.save()
        print('Created book!')


def handle_add(args):
    root = os.getcwd()
    path = get_book_file(root)
    book = None
    if path is None:
        p = os.path.join(root, CHAPTER_FILE)
        if find_book_file(root) is not None:
            if file_exist(p):
                path = p
                book = Chapter.load(path)
            else:
                print('Missing {}'.format(p))
                print('This is not a chapter folder!')
                return
        else:
            print('This is not a book!')
            return
    else:
        book = Book.load(path)

    if book is None:
        print('BUG: Book is None')
        return
    index_source = os.path.join(root, CHAPTER_INDEX)

    changed = False
    for chapter in args.chapters:
        chapter_path = os.path.join(root, chapter)
        if file_exist(chapter_path):
            if chapter_path == index_source:
                print('{} evaluates to the index file, this is always added, so ignoring...'.format(chapter))
                continue
            book.add_chapter(chapter)
            print("Adding {}".format(chapter))

            update_frontmatter_chapter(chapter_path)

            changed = True
        elif folder_exist(chapter_path):
            index_path = os.path.join(chapter_path, CHAPTER_INDEX)
            section_path = os.path.join(chapter_path, CHAPTER_FILE)
            if file_exist(index_path):
                if file_exist(section_path):
                    print('Existing section {} already added'.format(chapter))
                else:
                    print("Adding section {}".format(chapter))
                    chap = Chapter(section_path)
                    chap.save()
                    update_frontmatter_chapter(index_path)
                    book.add_chapter(chapter)
                    changed = True
            else:
                print("Missing section file: {}".format(index_path))
        else:
            print("File '{}' doesn't exist".format(chapter_path))

    if changed:
        book.save()


def handle_build(_):
    root = os.getcwd()
    ext = 'html'

    path = find_book_file(root)
    if path is None:
        print('This is not a book')
        return

    book = Book.load(path)
    book_folder = os.path.dirname(path)
    index_source = os.path.join(book_folder, CHAPTER_INDEX)
    html = os.path.join(book_folder, 'html')
    index_target = change_extension(os.path.join(html, CHAPTER_INDEX), ext)
    stat = Stat()
    templates = Templates(get_template_root(), ext)

    pages = []
    glob = book.generate_globals()
    root_page = book.generate_pages(html, ext, stat, pages)
    gen = GeneratedData(
        glob,
        ext,
        book_title=root_page.general.title,
        root=book_folder,
        toc=generate_toc([root_page] + root_page.children, ext, index_source, index_target),
        style_css=os.path.join(html, 'style.css'),
        index_html=os.path.join(html, 'index.html')
        )
    Page.post_generation(pages)

    copy_default_html_files(gen.style_css)
    for page in pages:
        page.write(templates, gen)

    # generate
    stat.print_estimate()


def handle_list(_):
    root = os.getcwd()
    path = find_book_file(root)
    if path is None:
        print('This is not a book')
        return

    book = Book.load(path)

    for md in book.iterate_markdown_files():
        print(md)


def handle_list_images(_):
    root = os.getcwd()
    path = find_book_file(root)
    if path is None:
        print('This is not a book')
        return

    book = Book.load(path)

    for md in book.iterate_markdown_files():
        _, content = read_frontmatter_file(md)
        for image in list_images_in_markdown(content):
            print(image)


###################################################################################################
###################################################################################################
###################################################################################################


def main():
    parser = argparse.ArgumentParser(description='Create or write a book')
    sub_parsers = parser.add_subparsers(dest='command_name', title='Commands', help='', metavar='<command>')

    sub = sub_parsers.add_parser('init', help='Create a new book')
    sub.add_argument('--update', action='store_true')
    sub.set_defaults(func=handle_init)

    sub = sub_parsers.add_parser('add', help='Add a thing to a book')
    sub.add_argument('chapters', nargs='+', metavar='chapter')
    sub.set_defaults(func=handle_add)

    sub = sub_parsers.add_parser('build', help='Generate html')
    sub.set_defaults(func=handle_build)

    list_parsers = sub_parsers.add_parser('list', help='List things').add_subparsers(dest='command_name', title='list commands', metavar='<command>')

    sub = list_parsers.add_parser('markdown', help='List all markdown files')
    sub.set_defaults(func=handle_list)

    sub = list_parsers.add_parser('images', help='List all images')
    sub.set_defaults(func=handle_list_images)

    args = parser.parse_args()
    if args.command_name is not None:
        args.func(args)
    else:
        parser.print_help()


###################################################################################################
###################################################################################################
###################################################################################################


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
