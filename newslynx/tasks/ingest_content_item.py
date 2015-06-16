
from newslynx.core import db
from newslynx.models import ExtractCache
from newslynx.models import (
    ContentItem, Tag, Recipe, Author)
from newslynx.models.util import (
    get_table_columns,
    fetch_by_id_or_field)
from newslynx.views.util import validate_content_item_types
from newslynx.exc import RequestError
from newslynx.tasks import ingest_util


extract_cache = ExtractCache()


def ingest_content_item(
        obj,
        org_id,
        url_fields=['body'],
        requires=['url', 'type'],
        extract=True):
    """
    Ingest an Event.
    """

    # check required fields
    ingest_util.check_requires(obj, requires, type='Content Item')

    # validate type
    validate_content_item_types(obj['type'])

    # check if the org_id is in the body
    # TODO: I don't think this is necessary.
    org_id = obj.pop('org_id', org_id)

    # get rid of ``id`` if it somehow got in here.
    obj.pop('id', None)

    # normalize the url
    obj['url'] = ingest_util.prepare_url(obj, 'url')

    # run article extraction.
    if extract:
        cache_response = extract_cache.get(url=obj['url'], type=obj['type'])
        if not cache_response:

            # make sure to kill this key.
            extract_cache.invalidate(url=obj['url'], type=obj['type'])
            raise RequestError(
                'Extraction failed on {type} - {url}'
                .format(**obj))
        # extraction succeeded
        else:
            data = cache_response.value
            obj.update(data)

    else:
        obj['title'] = ingest_util.prepare_str(obj, 'title')
        obj['description'] = ingest_util.prepare_str(obj, 'description')
        obj['body'] = ingest_util.prepare_str(obj, 'body')
        obj['created'] = ingest_util.prepare_str(obj, 'created')
        if not obj['created']:
            obj.pop('created')

    # split out tags_ids + authors + links
    tag_ids = obj.pop('tag_ids', [])
    authors = obj.pop('authors', []) # accept ids too
    # links = obj.pop('links', {})

    # determine event provenance
    data = _content_item_provenance(obj, org_id)

    # split out meta fields
    obj = ingest_util.split_meta(obj, get_table_columns(ContentItem))

    # see if the event already exists.
    c = ContentItem.query\
        .filter_by(org_id=org_id, type=obj['type'], url=obj['url'])\
        .first()

    # if not, create it
    if not c:

        # create event
        c = ContentItem(org_id=org_id, **obj)

    # else, update it
    else:
        for k, v in obj.items():
            setattr(c, k, v)

    # extract urls and normalize urls asynchronously.
    # urls = ingest_util.extract_urls(
    #     obj,
    #     url_fields,
    #     source=data.get('url'),
    #     links=_links)

    # detect content_items
    # if len(_links):
    #     c = _associate_content_items(c, org_id, _links)

    # associate tags
    if len(tag_ids):
        c = _associate_tags(c, org_id, tag_ids)

    # associate tags
    if len(authors):
        c = _associate_authors(c, org_id, authors)

    db.session.add(c)
    db.session.commit()
    return c


def _content_item_provenance(obj, org_id):
    """
    if there's not a recipe_id set the provenance as "manual"
    otherwise check it the recipe id is valid and set as "recipe"
    """

    if 'recipe_id' not in obj or not obj['recipe_id']:
        obj['provenance'] = 'manual'

    else:
        # fetch the associated recipe
        r = Recipe.query\
            .filter_by(id=obj['recipe_id'])\
            .filter_by(org_id=org_id)\
            .first()

        if not r:
            raise RequestError(
                'Recipe id "{recipe_id}" does not exist.'
                .format(**obj))
        # set this event as non-manual
        obj['provenance'] = 'recipe'

    return obj


def _associate_authors(c, org_id, authors):
    """
    Associate authors with a content item.
    """
    if not isinstance(authors, list):
        authors = [authors]
    for author in authors:
        try:
            int(author)
            is_name = False
        except ValueError:
            is_name = True

        if is_name:
            a = Author.query\
                .filter_by(name=author, org_id=org_id)\
                .first()
            if not a:
                a = Author(org_id=org_id, name=author)
        else:
            a = Author.query.get(author)

        # upsert
        if a and a.id not in c.author_ids:
            c.authors.append(a)
    return c


def _associate_tags(c, org_id, tag_ids):
    """
    Associate tags with a content item.
    """
    for tid in tag_ids:
        tag = fetch_by_id_or_field(Tag, 'slug', tid, org_id)
        if not tag:
            raise RequestError(
                'Tag with id/slug {} does not exist.'
                .format(tid))

        if tag:
            if tag.type != 'subject':
                raise RequestError(
                    'Only subject tags can be associated with Content Items. '
                    'Tag {} is of type {}'
                    .format(tag.id, tag.type))

        # upsert
        if tag.id not in c.tag_ids:
            c.tags.append(tag)
    return c

# def _associate_content_items(c, org_id, urls):
#     """
#     Check if event has associations with content items.
#     """
#     content_items = ContentItem.query\
#         .filter(ContentItem.url.in_(urls))\
#         .filter(ContentItem.org_id == org_id)\
#         .all()

#     if len(content_items):

#         # upsert content_items.
#         for t in content_items:
#             if t.id not in c.out_link_ids:
#                 c.out_links.append(t)
#     return c


# def _prepare_links_for_checking(links, data):
#     _links = []
#     for k, v in links.items():
#         if k == 'articles':
#             if 'internal' in v and len(v['internal']):
#                 for u in v['internal']:
#                     if not (u == data['url'] or data['url'] in u):
#                         o = {
#                             'url': u
#                         }
#                         u = ingest_util.prepare_url(o, field='url', source=data['url'])
#                         if u:
#                             _links.extend(u)
#     return _links
