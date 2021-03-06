#!/usr/bin/env python3
# Converts from the source markup format to HTML for the web version.


# todo(Gustav): support epub
# todo(Gustav): fix and validate internal links
# todo(Gustav): html in page title when title is markdowned
# todo(Gustav): commands to move markdowns/pages between folders/chapters
# todo(Gustav): add graphviz image generation
# todo(Gustav): add watcher (with auto refresh like hugo)
# todo(Gustav): action change image format and make black-white and dithering

###################################################################################################
# Imports

import os
import typing
import argparse
import time
import json
import re
import urllib
import urllib.request
import shutil
import logging
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


logging.basicConfig(level=logging.WARNING, format="%(msg)s")
LOG = logging.getLogger('logtest')

###################################################################################################
# Constants

# single file in book root
BOOK_FILE = '.book.json'

# a folder (or file) that is added to a book is considered a chapter
CHAPTER_FILE = '.chapter.json'

# a markdown that is automatically added to the folder first
# index or readme? readme.md goes nice with github browsing but index.html is another standard
CHAPTER_INDEX = 'index.md'

TOC_INDEX = 'toc.md'

#  special html syntax to hack in toc in a generated page
TOC_HTML_BODY = '__toc_html_body__'

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
    LOG.debug(f'reading {path}')
    with open(path, 'r', encoding='utf-8') as input_file:
        return input_file.read()


def read_frontmatter_file(path: str, missing_is_error: bool = True) -> typing.Tuple[typing.Any, str]:
    has_frontmatter = False
    first = []
    second = []
    if not missing_is_error and not file_exist(path):
        return (None, '')
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
                LOG.error(f"Parse error: {path}: {e}")
            return (frontmatter, ''.join(second))
        else:
            return (None, ''.join(first))


def frontmatter_to_string(frontmatter:typing.Optional[typing.Any]) -> str:
    if frontmatter is not None:
        return toml.dumps(frontmatter).rstrip()
    else:
        return ''


def write_frontmatter_file(path: str, frontmatter:typing.Optional[typing.Any], content:str):
    LOG.debug(f'Writing {path}')
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as file_handle:
        if frontmatter is not None:
            print(toml.dumps(frontmatter).rstrip(), file=file_handle)
            print(FRONTMATTER_SEPERATOR_CHAR * FRONTMATTER_SEPERATOR_MIN_LENGTH, file=file_handle)
        print(content.rstrip(), file=file_handle)


def write_file(contents: str, path: str) -> str:
    LOG.debug(f'Writing {path}')
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as file_handle:
        print(contents, file=file_handle)


def touch_file(path: str):
    if not file_exist(path):
        write_file('', path)


re_subscript = re.compile(r'\[([^\]]+)\]\{\.subscript\}')
re_superscript = re.compile(r'\[([^\]]+)\]\{\.superscript\}')

def math_to_html(content: str, regex, html: str) -> str:
    def replce_math(match):
        thing = match.group(1)
        return '<{}>{}</{}>'.format(html, thing, html)
    return regex.sub(replce_math, content)

def run_markdown(contents: str):
    cc = contents
    cc = math_to_html(cc, re_subscript, 'sub')
    cc = math_to_html(cc, re_superscript, 'sup')
    body = markdown.markdown(cc, extensions=['extra', 'def_list', 'codehilite'])
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
        LOG.debug(f'{filename}: {e}')
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
re_image = re.compile(r'!\[([^\]]*)\]\(([^)]+)\)')
re_image_alt = 1
re_image_url = 2

def list_images_in_markdown(md: str) -> typing.Iterable[str]:
    for match in re_image.finditer(md):
        yield match.group(re_image_url)


def replace_image_in_markdown(md: str, path: str, replacements: typing.Dict[str, str]) -> str:
    def replace_image_with_replacement(match):
        orig = match.group(0)
        alt_text = match.group(re_image_alt)
        orig_url = match.group(re_image_url)
        if orig_url in replacements:
            new_url = make_relative(path, replacements[orig_url])
            new_image = '![{}]({})'.format(alt_text, new_url)
            LOG.debug(f'replacing image {orig} -> {new_image}')
            return new_image
        else:
            return orig
    return re_image.sub(replace_image_with_replacement, md)


###################################################################################################
###################################################################################################
###################################################################################################


class Templates:
    def __init__(self, folder: str, ext: str):
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
                LOG.info(f"    {name}")
            elif word_count < 2000:
                self.empty_chapters += 1
                LOG.info(f"{Fore.YELLOW}-{Style.RESET_ALL} {name} ({word_count} words)")
            else:
                self.total_words += word_count
                LOG.info(f"{Fore.GREEN}✓{Style.RESET_ALL} {name} ({word_count} words)")
        else:
            # Section header chapters aren't counted like regular chapters.
            LOG.info(f"{Fore.GREEN}•{Style.RESET_ALL} {name} ({word_count} words)")

    def print_estimate(self):
        valid_chapters = self.num_chapters - self.empty_chapters
        average_word_count = self.total_words / valid_chapters if valid_chapters > 0 else 0
        estimated_word_count = self.total_words + (self.empty_chapters * average_word_count)
        percent_finished = self.total_words * 100 / estimated_word_count if estimated_word_count > 0 else 0

        LOG.info(f"{self.total_words}/~{estimated_word_count} words ({percent_finished}%)")


class GlobalData:
    def __init__(self, the_copyright: str):
        # todo(Gustav): add support to write markdown in copyright (or just a footer)
        self.copyright = the_copyright


class GeneratedData:
    def __init__(self, glob: GlobalData, extension: str, book_title: str, root: str, toc: str, style_css: str, index_html: str, toc_html: str):
        self.glob = glob
        self.extension = extension
        self.book_title = book_title
        self.root = root
        self.toc = toc
        self.style_css = style_css
        self.index_html = index_html
        self.toc_html = toc_html


class GuessedData:
    def __init__(self, source: str, title: typing.Optional[str] = None):
        if title is not None:
            self.title = title
        else:
            base = os.path.basename(source)
            if base == CHAPTER_INDEX:
                parent = os.path.abspath(os.path.join(source, os.pardir))
                base = os.path.basename(parent)
                self.title = base
            else:
                self.title = os.path.splitext(base)[0]


TOML_GENERAL_TITLE = 'title'


class ParsedFrontmatter:
    def __init__(self, frontmatter: typing.Any, guess: GuessedData):
        self.title = get_toml(frontmatter, TOML_GENERAL_TITLE, guess.title)

    def generate(self, frontmatter: typing.Any):
        frontmatter[TOML_GENERAL_TITLE] = self.title


def drop_p_tag(html: str) -> str:
    s = html.strip()
    if s.startswith('<p>') and s.endswith('</p>'):
        return s[3:-4]
    else:
        return s


class Page:
    def __init__(self, chapter: str, source: str, target: str, html_body: str, title: str):
        self.source = source
        self.target = target
        self.title = drop_p_tag(run_markdown(title))
        self.html_body = html_body
        self.chapter = chapter
        self.next_page = None
        self.prev_page = None
        self.parent = None
        self.children = []

    @staticmethod
    def from_file(stat: Stat, chapter: str, source: str, target: str, is_chapter: bool) -> 'Page':
        frontmatter, content = read_frontmatter_file(source)
        guess = GuessedData(source)
        general = ParsedFrontmatter(frontmatter, guess)
        html_body = run_markdown(content)
        title = general.title
        stat.update(content, chapter, is_chapter)
        return Page(chapter, source, target, html_body, title)

    @staticmethod
    def post_generation(pages: typing.List['Page']):
        last_page = None
        for page in pages:
            page.prev_page = last_page
            if last_page is not None:
                last_page.next_page = page
            last_page = page

    def write(self, templates: Templates, gen: GeneratedData):
        data = {}
        template = templates.template

        titles = [{"title": self.title}]
        section_headers = []

        p = self.parent
        while p is not None:
            if p.parent is not None:
                titles.append({"title": p.title})
                section_href = make_relative(self.target, p.target)
                section_headers.append({'title': p.title, 'href': section_href})
            p = p.parent
        section_headers.reverse()

        prev_page = '' if self.prev_page is None else make_relative(self.target, self.prev_page.target)
        next_page = '' if self.next_page is None else make_relative(self.target, self.next_page.target)

        data['body'] = gen.toc if self.html_body == TOC_HTML_BODY else self.html_body
        data['no_title_page'] = self.title != "Colophon"
        data['title'] = self.title
        data['titles'] = titles
        data['section_headers'] = section_headers
        data['header'] = self.title
        data['prev'] = prev_page
        data['next'] = next_page
        data['index_html'] = make_relative(self.target, gen.index_html)
        data['toc_html'] = make_relative(self.target, gen.toc_html)
        data['style_css'] = make_relative(self.target, gen.style_css)
        data['book_title'] = gen.book_title
        data['copyright'] = gen.glob.copyright

        generated = pystache_render(self.source, template, data)
        write_file(generated, self.target)

    def generate_html_list(self, extension: str, indent: str, file: str):
        html = indent + '<li><a href="{}">{}</a>'.format(make_relative(file, self.target), self.title)
        if len(self.children) > 0:
            html += '\n' + indent + '    <ul>\n'
            for c in self.children:
                html += c.generate_html_list(extension, indent + '    ', file) + '\n'
            html += indent + '    </ul>\n' + indent
        html += '</li>'
        return html


def strip_empty_start(lines: typing.Iterable[str]) -> typing.Iterable[str]:
    empty = True
    for li in lines:
        if len(li.strip()) == 0:
            if empty:
                pass
            else:
                yield li
        else:
            empty = False
            yield li


def strip_empty(lines: typing.List[str]) -> typing.List[str]:
    cleared = lines
    cleared.reverse()
    cleared = list(strip_empty_start(cleared)) # end
    cleared.reverse()
    cleared = list(strip_empty_start(cleared)) # start
    return cleared


def update_frontmatter(chapter_path: str, guess_arg: typing.Optional[GuessedData], extra_content: typing.Optional[str]):
    frontmatter, content = read_frontmatter_file(chapter_path, missing_is_error=False)
    write_chapter = False
    if frontmatter is None:
        write_chapter = True
        frontmatter = {}
        guess = guess_arg or GuessedData(chapter_path)
        chapter = ParsedFrontmatter(frontmatter, guess)
        chapter.generate(frontmatter)
    else:
        fmo = frontmatter_to_string(frontmatter)
        guess = guess_arg or GuessedData(chapter_path)
        chapter = ParsedFrontmatter(frontmatter, guess)
        chapter.generate(frontmatter)
        if fmo != frontmatter_to_string(frontmatter):
            write_chapter = True
    if write_chapter or extra_content is not None:
        cc = strip_empty(content.splitlines())
        if extra_content is not None:
            cc = cc + [''] + strip_empty(extra_content.splitlines())
        cc = strip_empty(cc)
        write_frontmatter_file(chapter_path, frontmatter, '\n'.join(cc))


def update_frontmatter_chapter(chapter_path: str, guess: typing.Optional[GuessedData] = None, content: typing.Optional[str] = None):
    update_frontmatter(chapter_path, guess, content)


def update_frontmatter_index(chapter_path: str):
    update_frontmatter(chapter_path, None, '')


def create_page(stat: Stat, chapter: str, source_folder: str, target_folder: str, ext: str) -> Page:
    source = os.path.join(source_folder, chapter)
    target = os.path.join(target_folder, change_extension(chapter, ext) if file_exist(source) else chapter)
    book_index_file = os.path.join(os.path.dirname(find_book_file(source_folder)), CHAPTER_INDEX)
    is_index = source == book_index_file
    is_chapter = chapter == CHAPTER_INDEX
    return Page.from_file(stat, chapter, source, target, is_chapter)


class Chapter:
    def __init__(self, file_path: str):
        self.chapters = []
        self.file_path = file_path
        self.source_folder = os.path.dirname(file_path)

    def add_chapter(self, chap: str, add_at_start: bool = False):
        if add_at_start:
            self.chapters.insert(0, chap)
        else:
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
        chapter_index_file = os.path.join(self.source_folder, CHAPTER_INDEX)
        if not file_exist(chapter_index_file):
            LOG.error(f'{chapter_index_file}: file not found')

        root_page = create_page(stat, CHAPTER_INDEX, self.source_folder, target_folder, ext)
        pages.append(root_page)

        book_index_file = os.path.join(os.path.dirname(find_book_file(self.source_folder)), CHAPTER_INDEX)

        for chapter in self.chapters:
            source = os.path.join(self.source_folder, chapter)
            is_special_toc = chapter == TOC_INDEX
            target = os.path.join(target_folder, change_extension(chapter, ext) if file_exist(source) or is_special_toc else chapter)
            if file_exist(source) or is_special_toc:
                is_index = source == book_index_file
                is_chapter = chapter == CHAPTER_INDEX
                child_page = Page.from_file(stat, chapter, source, target, is_chapter) if not is_special_toc else Page(chapter, source, target, TOC_HTML_BODY, 'Table of Contents')
                pages.append(child_page)
                root_page.children.append(child_page)
                child_page.parent = root_page
            elif folder_exist(source):
                section_file = os.path.join(source, CHAPTER_FILE)
                if file_exist(section_file):
                    section = Chapter.load(section_file)
                    child_page = section.generate_pages(target, ext, stat, pages)

                    root_page.children.append(child_page)
                    child_page.parent = root_page
                else:
                    LOG.error(f'{section_file} missing file')
            else:
                LOG.error(f'{source}: Neither file nor folder')

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
        is_book = file_exist(os.path.join(self.source_folder, BOOK_FILE))
        index_file = os.path.join(self.source_folder, CHAPTER_INDEX)
        if is_book:
            update_frontmatter_index(index_file)

            fm, _ = read_frontmatter_file(index_file)
            guess = GuessedData(index_file)
            data = ParsedFrontmatter(fm, guess)
        else:
            update_frontmatter_chapter(index_file)

        for chapter in self.chapters:
            path = os.path.join(self.source_folder, chapter)
            update_frontmatter_chapter(path)



def generate_toc(pages: typing.List[Page], extension: str, index_source: str, target: str) -> str:
    html = ''

    # add only pages after toc, or if toc is missing then add all
    children = []
    found_toc = False
    for c in pages:
        if found_toc:
            children.append(c)
        if c.html_body == TOC_HTML_BODY:
            found_toc = True
    children = pages if len(children) == 0 and not found_toc else children

    for page in children:
        if page.source != index_source:
            html = html + page.generate_html_list(extension, '  ', target)
    return html


class Book(Chapter):
    def __init__(self, file_path: str):
        Chapter.__init__(self, file_path)
        self.chapters.append(TOC_INDEX)
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
            data = ParsedFrontmatter(frontmatter, GuessedData(chapter_path))
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
            LOG.error(f'Book is already defined in {path}')
            return
        book = Book.load(path)
        book.update_frontmatters()
    else:
        path = book_path_in_folder(root)
        book = Book(path)
        book.save()
        book.update_frontmatters()
        LOG.info('Created book!')


def get_book_or_chapter(root: str) -> typing.Optional[Chapter]:
    path = get_book_file(root)
    book = None
    if path is None:
        p = os.path.join(root, CHAPTER_FILE)
        if find_book_file(root) is not None:
            if file_exist(p):
                path = p
                book = Chapter.load(path)
            else:
                LOG.error(f'{p}: Missing file. This is not a valid chapter folder!')
                return None
        else:
            LOG.error('This is not a book!')
            return None
    else:
        book = Book.load(path)

    if book is None:
        LOG.debug('BUG: Book is None')
        return None
    else:
        return book


REORDER_LAST = "last"
REORDER_AFTER_TOC = "after_toc"
REORDER_BEFORE_TOC = "before_toc"

def handle_reorder(args):
    where = args.where
    book = get_book_or_chapter(os.getcwd())
    if book is None:
        return

    changed = False
    if where == REORDER_AFTER_TOC:
        args.chapters.reverse()
    for chapter in args.chapters:
        if chapter not in book.chapters:
            LOG.error(f'Unable to find {chapter} in book')
            return

        s = len(book.chapters)
        book.chapters.remove(chapter)
        if len(book.chapters) != s:
            changed = True

        if where == REORDER_LAST:
            book.chapters.append(chapter)
        elif where == REORDER_AFTER_TOC:
            if TOC_INDEX in book.chapters:
                toc = book.chapters.index(TOC_INDEX)
                book.chapters.insert(toc+1, chapter)
            else:
                LOG.info('missing toc, adding last')
                book.chapters.add(chapter)
        elif where == REORDER_BEFORE_TOC:
            if TOC_INDEX in book.chapters:
                toc = book.chapters.index(TOC_INDEX)
                book.chapters.insert(toc, chapter)
            else:
                LOG.info('missing toc, adding last')
                book.chapters.add(chapter)
        else:
            LOG.error('Unknown action, adding last')
            book.chapters.add(chapter)


    if changed:
        book.save()


def handle_move(args):
    book = get_book_or_chapter(args.destination)
    if book is None:
        return

    changed = False
    for relative_chapter in args.chapters:
        path = os.path.realpath(relative_chapter)
        folder = os.path.dirname(path)
        chapter = os.path.split(path)[1]
        chapter_book = get_book_or_chapter(folder)
        if chapter not in chapter_book.chapters:
            LOG.error(f'Unable to find {chapter} in book {folder}')
            return

        fm, content = read_frontmatter_file(path)
        os.remove(path)

        new_path = os.path.join(args.destination, chapter)
        content = update_images(path, new_path, content)
        write_frontmatter_file(new_path, fm, content)

        book.chapters.append(chapter)
        changed = True

    if changed:
        book.save()

def handle_remove(args):
    book = get_book_or_chapter(os.getcwd())
    if book is None:
        return

    changed = False
    for chapter in args.chapters:
        chapter_path = os.path.join(book.source_folder, chapter)

        if chapter not in book.chapters:
            LOG.error(f'Unable to find {chapter} in book')
            return

        s = len(book.chapters)
        book.chapters.remove(chapter)
        if len(book.chapters) != s:
            changed = True
            LOG.info(f'Removed {chapter}')

        if file_exist(chapter_path):
            os.remove(chapter_path)
        elif folder_exist(chapter_path):
            shutil.rmtree(chapter_path, ignore_errors=True)

    if changed:
        book.save()

def handle_add(args):
    book = get_book_or_chapter(os.getcwd())
    if book is None:
        return

    index_source = os.path.join(book.source_folder, CHAPTER_INDEX)

    changed = False
    for chapter in args.chapters:
        chapter_path = os.path.join(book.source_folder, chapter)
        if file_exist(chapter_path):
            if chapter_path == index_source:
                LOG.info(f'{chapter} evaluates to the index file, this is always added, so ignoring...')
                continue
            book.add_chapter(chapter)
            LOG.info(f"Adding {chapter}")

            update_frontmatter_chapter(chapter_path)

            changed = True
        elif folder_exist(chapter_path):
            index_path = os.path.join(chapter_path, CHAPTER_INDEX)
            section_path = os.path.join(chapter_path, CHAPTER_FILE)
            if file_exist(section_path):
                LOG.error(f'Existing section {chapter} already added')
            else:
                LOG.info(f"Adding section {chapter}")
                chap = Chapter(section_path)
                chap.save()
                update_frontmatter_chapter(index_path)
                book.add_chapter(chapter)
                changed = True
        else:
            LOG.error(f"File '{chapter_path}' doesn't exist")

    if changed:
        book.save()


def name_from_title(title: str) -> str:
    t = title
    t = t.lower()
    t = t.replace(' ', '_')
    t = t.replace('.', '')
    t = t.replace('*', '')
    t = t.replace(':', '')
    t = t.replace(',', '')
    t = t.replace('(', '')
    t = t.replace(')', '')
    t = t.replace('?', '')
    t = t.replace('/', '-')
    return t


def new_page(book: Chapter, title: str, content: str, add_at_start: bool = False) -> bool:
    chapter = name_from_title(title) + '.md'
    chapter_path = os.path.join(book.source_folder, chapter)
    if file_exist(chapter_path):
        LOG.info(f'{chapter} already exists, so ignoring...')
        return False
    book.add_chapter(chapter, add_at_start)
    update_frontmatter_chapter(chapter_path, GuessedData(source=chapter_path, title=title), content=content)
    return True


def handle_new_page(args):
    book = get_book_or_chapter(os.getcwd())
    if book is None:
        return

    for title in args.pages:
        if new_page(book ,title, ''):
            changed = True

    if changed:
        book.save()


def line_contains(line: str, on: typing.Optional[str]) -> bool:
    if on is None:
        return True
    return on.lower() in line.lower()


re_markdown_header = re.compile(r'^#[^#]* ')
re_markdown_header_tag = re.compile(r'\{#[^}]+\}')

def markdown_extract_pages_from_lines(file: typing.Iterable[str], on: typing.Optional[str]=None) -> typing.Iterable[typing.Tuple[str, typing.List[str]]]:
    header = None
    lines = []
    for line_space in file:
        line = line_space.rstrip()
        if line.startswith('# ') and line_contains(line, on):
            if header is None:
                lines = strip_empty(lines)
                if len(lines) > 0:
                    yield ('', lines)
            else:
                stripped = strip_empty(lines)
                if len(stripped) != 0:
                    yield (header, stripped)
            lines = []
            header = re_markdown_header_tag.sub('', line[1:].strip()).strip()
        else:
            if re_markdown_header.match(line) is not None and on is None:
                line = line[1:]
            lines.append(line)
    if header is not None:
        stripped = strip_empty(lines)
        if len(stripped) != 0:
            yield (header, stripped)


def markdown_extract_pages_from_file(path: str) -> typing.Iterable[typing.Tuple[str, typing.List[str]]]:
    with open(path) as file:
        lines = file.readlines()
        return markdown_extract_pages_from_lines(lines)


def update_images(from_path: str, to_path: str, md: str) -> str:
    from_folder = os.path.dirname(from_path)
    replacements = {}
    for image in list_images_in_markdown(md):
        image_path = os.path.join(from_folder, image)
        if file_exist(image_path):
            # new_image = make_relative(to_path, image_path)
            replacements[image] = image_path
            LOG.debug(f'replacing {image} with {image_path}')
        else:
            LOG.warning(f'WARNING: ignoring missing image {image_path}')

    LOG.debug(f"   replaced {len(replacements)} images")
    return replace_image_in_markdown(md, to_path, replacements)


def handle_split_markdown(args):
    root = os.getcwd()
    book = get_book_or_chapter(root)
    if book is None:
        LOG.error('This is not a book, consider using import instead')
        return

    book_has_only_toc = len(book.chapters) == 1 and TOC_INDEX in book.chapters

    for args_file in args.files:
        from_file_path = os.path.join(book.source_folder, args_file)
        frontmatter, content = read_frontmatter_file(from_file_path)
        pages = list(markdown_extract_pages_from_lines(content.splitlines(), args.on))

        if args.print:
            for data in pages:
                title, lines = data
                file_name = name_from_title(title) + '.md' if len(title) > 0 else '<unchanged>'
                LOG.info(f'{title} ({len(lines)}) -> {file_name}')
            return
        else:
            if len(pages)==0:
                LOG.error('Zero pages found.')
                return

        remaining_content = ''
        first_title, first_content = pages[0]
        if len(first_title.strip()) == 0:
            remaining_content = '\n'.join(first_content)
            pages = pages[1:]

        if len(pages) == 0:
            LOG.error('Only title page found... aborting')
            return

        if args_file == CHAPTER_INDEX:
            write_frontmatter_file(from_file_path, frontmatter, remaining_content)
            if not book_has_only_toc:
                # since we add to the start, we need to go in reverse
                pages.reverse()
            for data in pages:
                title, lines = data
                new_page(book, title, '\n'.join(lines), add_at_start=not book_has_only_toc)

            book.save()
        else:
            if args_file not in book.chapters:
                LOG.error('This is not a page in a chapter!')
                return

            original_page_file = os.path.join(book.source_folder, args_file)
            dir_name = os.path.splitext(args_file)[0]
            dir_path = os.path.join(book.source_folder, dir_name)

            # replace page with chapter in book
            book.chapters = [dir_name if chap==args_file else chap for chap in book.chapters]

            # remove original page
            os.unlink(original_page_file)

            # create chapter directory
            if not os.path.isdir(dir_path):
                os.mkdir(dir_path)

            sub_chapter_index = os.path.join(dir_path, CHAPTER_FILE)
            chapter = Chapter(sub_chapter_index)

            # create chapter index with title and remaining content
            chapter_path = os.path.join(dir_path, CHAPTER_INDEX)
            chapter_title = ParsedFrontmatter(frontmatter, GuessedData(chapter_path)).title
            update_frontmatter_chapter(chapter_path, GuessedData(chapter_path, chapter_title), update_images(from_file_path, chapter_path, remaining_content))

            # add split pages in sub chapter
            for data in pages:
                title, lines = data
                page_file = os.path.join(chapter.source_folder, name_from_title(title) + '.md')
                new_page(chapter, title, update_images(from_file_path, page_file, '\n'.join(lines)))

            chapter.save()
            book.save()


def handle_indent_markdown(args):
    root = os.getcwd()
    book = get_book_or_chapter(root)
    if book is None:
        LOG.error('This is not a book, consider using import instead')
        return
    for args_file in args.files:
        from_file_path = os.path.join(book.source_folder, args_file)
        frontmatter, content = read_frontmatter_file(from_file_path)

        lines = content.splitlines()
        if any(line.startswith('# ') for line in lines):
            newlines = ['#' + line if re_markdown_header.match(line) is not None else line for line in lines]
            write_frontmatter_file(from_file_path, frontmatter, '\n'.join(newlines))


def handle_import_markdown(args):
    root = os.getcwd()
    path = os.path.abspath(args.file)
    if not file_exist(path):
        LOG.error(f'{path}: Missing file ')
        return
    pages = list(markdown_extract_pages_from_file(path))

    if args.print:
        for data in pages:
            title, lines = data
            LOG.info('{} ({})'.format(title, len(lines)))
    else:
        if len(pages) > 1:
            LOG.error('Unable to create a book from {}'.format(path))
            return

        path = find_book_file(root)
        if path is not None:
            LOG.error('This is a book, importing will create a new book')
            return

        index_file = os.path.join(root, CHAPTER_INDEX)
        title, lines = pages[0]
        frontmatter = {}
        guess = GuessedData(index_file, title)
        data = ParsedFrontmatter({}, guess)
        data.generate(frontmatter)
        write_frontmatter_file(index_file, frontmatter, '\n'.join(lines))

        path = book_path_in_folder(root)
        book = Book(path)
        book.save()
        book.update_frontmatters()





def handle_build(_):
    root = os.getcwd()
    ext = 'html'

    path = find_book_file(root)
    if path is None:
        LOG.error('This is not a book')
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
        book_title=root_page.title,
        root=book_folder,
        toc=generate_toc([root_page] + root_page.children, ext, index_source, index_target),
        style_css=os.path.join(html, 'style.css'),
        index_html=os.path.join(html, 'index.html'),
        toc_html=os.path.join(html, 'toc.html')
        )
    Page.post_generation(pages)

    copy_default_html_files(gen.style_css)
    for page in pages:
        page.write(templates, gen)

    for md in book.iterate_markdown_files():
        _, content = read_frontmatter_file(md)
        markdown_folder = os.path.dirname(md)
        relative = make_relative(book.file_path, markdown_folder)
        for image in list_images_in_markdown(content):
            url = urllib.parse.urlparse(image)
            if url.scheme == '':
                # image_name = os.path.basename(url.path)
                image_name = url.path
                source_path = os.path.normpath(os.path.join(markdown_folder, image_name))
                target_path = os.path.normpath(os.path.realpath(os.path.join(html, relative, image_name)))
                os.makedirs(os.path.dirname(target_path), exist_ok=True)
                LOG.debug(f'Copying {os.path.basename(target_path)}')
                shutil.copyfile(source_path, target_path)

    # generate
    stat.print_estimate()


def handle_list(_):
    root = os.getcwd()
    path = find_book_file(root)
    if path is None:
        LOG.error('This is not a book')
        return

    book = Book.load(path)

    for md in book.iterate_markdown_files():
        LOG.info(md)


def handle_list_images(_):
    root = os.getcwd()
    path = find_book_file(root)
    if path is None:
        LOG.error('This is not a book')
        return

    book = Book.load(path)

    for md in book.iterate_markdown_files():
        _, content = read_frontmatter_file(md)
        for image in list_images_in_markdown(content):
            LOG.info(image)


def handle_make_local(_):
    root = os.getcwd()
    path = find_book_file(root)
    if path is None:
        LOG.error('This is not a book')
        return

    book = Book.load(path)

    images = {}

    markdown_files = list(book.iterate_markdown_files())

    for md in markdown_files:
        _, content = read_frontmatter_file(md)
        markdown_folder = os.path.dirname(md)
        for image in list_images_in_markdown(content):
            url = urllib.parse.urlparse(image)
            if url.scheme != '':
                image_name = os.path.basename(url.path)
                target_path = os.path.join(markdown_folder, image_name)
                if file_exist(target_path):
                    LOG.error(f'{md}: Image {image_name} already exists')
                images[image] = target_path

    for md in markdown_files:
        frontmatter, content = read_frontmatter_file(md)
        content = replace_image_in_markdown(content, md, images)
        write_frontmatter_file(md, frontmatter, content)

    for source, dest in images.items():
        if not file_exist(dest):
            urllib.request.urlretrieve(source, dest)

    LOG.info(f'{len(images)} replacements made')

###################################################################################################
###################################################################################################
###################################################################################################


def main():
    parser = argparse.ArgumentParser(description='Create or write a book')
    sub_parsers = parser.add_subparsers(dest='command_name', title='Commands', help='', metavar='<command>')

    sub = sub_parsers.add_parser('init', help='Create a new book')
    sub.add_argument('--update', action='store_true')
    sub.set_defaults(func=handle_init)

    sub = sub_parsers.add_parser('add', help='Add a existing page or chapter to a book')
    sub.add_argument('chapters', nargs='+', metavar='chapter')
    sub.set_defaults(func=handle_add)

    sub = sub_parsers.add_parser('rm', help='Remove existing page or chapter')
    sub.add_argument('chapters', nargs='+', metavar='chapter')
    sub.set_defaults(func=handle_remove)

    sub = sub_parsers.add_parser('new', help='Add a new page to a book')
    sub.add_argument('pages', nargs='+', metavar='page')
    sub.set_defaults(func=handle_new_page)

    sub = sub_parsers.add_parser('import', help='Import book from markdown')
    sub.add_argument('file')
    sub.add_argument('--print', action='store_true')
    sub.set_defaults(func=handle_import_markdown)

    sub = sub_parsers.add_parser('reorder', help='Reorder pages or chapters in current book')
    sub.add_argument('where', choices=[REORDER_LAST, REORDER_BEFORE_TOC, REORDER_AFTER_TOC])
    sub.add_argument('chapters', nargs='+', metavar='chapter')
    sub.set_defaults(func=handle_reorder)

    sub = sub_parsers.add_parser('move', help='Move pages or chapters in current book')
    sub.add_argument('--destination', default=os.getcwd())
    sub.add_argument('chapters', nargs='+', metavar='chapter')
    sub.set_defaults(func=handle_move)

    sub = sub_parsers.add_parser('split', help='Split a existing chapter or page to several pages or chapters')
    sub.add_argument('files', nargs='+', metavar='file')
    sub.add_argument('--print', action='store_true')
    sub.add_argument('--on', default=None, help='extra argument in title that is required')
    sub.set_defaults(func=handle_split_markdown)

    sub = sub_parsers.add_parser('indent', help='indent headers so that they are no longer toplevel')
    sub.add_argument('files', nargs='+', metavar='file')
    sub.set_defaults(func=handle_indent_markdown)

    sub = sub_parsers.add_parser('build', help='Generate html')
    sub.set_defaults(func=handle_build)

    sub = sub_parsers.add_parser('make_local', help='Download external image and update markdown')
    sub.set_defaults(func=handle_make_local)

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
