import sys
import os
import re
import datetime
import pytz
import yaml
import urlparse

from random import Random
from r2.models import Link,Comment,Account,Subreddit
from r2.models.account import AccountExists, register
from r2.lib.db.thing import NotFound

###########################
# Constants
###########################

MAX_RETRIES = 100

# Constants for the characters to compose a password from.
# Easilty confused characters like I and l, 0 and O are omitted
PASSWORD_NUMBERS='123456789'
PASSWORD_LOWER_CHARS='abcdefghjkmnpqrstuwxz'
PASSWORD_UPPER_CHARS='ABCDEFGHJKMNPQRSTUWXZ'
PASSWORD_OTHER_CHARS='@#$%^&*'
ALL_PASSWORD_CHARS = ''.join([PASSWORD_NUMBERS,PASSWORD_LOWER_CHARS,PASSWORD_UPPER_CHARS,PASSWORD_OTHER_CHARS])

DATE_FORMAT = '%m/%d/%Y %I:%M:%S %p'
INPUT_TIMEZONE = pytz.timezone('America/New_York')

rng = Random()
def generate_password():
    password = []
    for i in range(8):
        password.append(rng.choice(ALL_PASSWORD_CHARS))
    return ''.join(password)

class Importer(object):

    def __init__(self, url_handler=None):
        """Constructs an importer that takes a data structure based on a yaml file.

        Args:
        url_handler: A optional URL transformation function that will be
        called with urls detected in post and comment bodies.
        """

        self.url_handler = url_handler if url_handler else self._default_url_handler

        self.username_mapping = {}

    @staticmethod
    def _default_url_handler(match):
        return match.group()

    def process_comment(self, comment_data, comment, post, comment_dictionary):
        # Prepare data for import
        ip = '127.0.0.1'
        if comment_data:
            naive_date = datetime.datetime.strptime(comment_data['dateCreated'], DATE_FORMAT)
            local_date = INPUT_TIMEZONE.localize(naive_date, is_dst=False) # Pick the non daylight savings time
            utc_date = local_date.astimezone(pytz.utc)

            # Determine account to use for this comment
            account = self._get_or_create_account(comment_data['author'], comment_data['authorEmail'])

        if comment_data and not comment_data['author'].endswith("| The Effective Altruism Blog"):
            if not comment:
                # Create new comment
                comment, inbox_rel = Comment._new(account, post, None, comment_data['body'], ip, date=utc_date)
                if str(comment_data['commentParent']) in comment_dictionary:
                    comment.parent_id = comment_dictionary[str(comment_data['commentParent'])]
                comment.is_html = True
                comment.ob_imported = True
                comment._commit()
                comment_dictionary[str(comment_data['commentId'])] = comment._id
            else:
                # Overwrite existing comment
                if str(comment_data['commentParent']) in comment_dictionary:
                    comment.parent_id = comment_dictionary[str(comment_data['commentParent'])]
                comment.author_id = account._id
                comment.body = comment_data['body']
                comment.ip = ip
                comment._date = utc_date
                comment.is_html = True
                comment.ob_imported = True
                comment._commit()
                comment_dictionary[str(comment_data['commentId'])] = comment._id

    kill_tags_re = re.compile(r'</?[iub]>')
    transform_categories_re = re.compile(r'[- ]')

    def process_post(self, post_data, sr):
        # Prepare data for import
        title = self.kill_tags_re.sub('', post_data['title'])
        article = u'%s%s' % (post_data['description'],
                             Link._more_marker + post_data['mt_text_more'] if post_data['mt_text_more'] else u'')
        ip = '127.0.0.1'
        tags = [self.transform_categories_re.sub('_', tag.lower()) for tag in post_data.get('category', [])]
        naive_date = datetime.datetime.strptime(post_data['dateCreated'], DATE_FORMAT)
        local_date = INPUT_TIMEZONE.localize(naive_date, is_dst=False) # Pick the non daylight savings time
        utc_date = local_date.astimezone(pytz.utc)

        # Determine account to use for this post
        account = self._get_or_create_account(post_data['author'], post_data['authorEmail'])

        # Look for an existing post created due to a previous import
        post = self._query_post(Link.c.ob_permalink == post_data['permalink'])

        if not post:
            # Create new post
            post = Link._submit(title, article, account, sr, ip, tags, date=utc_date)
            post.blessed = True
            post.comment_sort_order = 'old'
            post.ob_permalink = post_data['permalink']
            post._commit()
        else:
            # Update existing post
            post.title = title
            post.article = article
            post.author_id = account._id
            post.sr_id = sr._id
            post.ip = ip
            post.set_tags(tags)
            post._date = utc_date
            post.blessed = True
            post.comment_sort_order = 'old'
            post._commit()

        # Process each comment for this post
        comment_dictionary = {}
        comments = self._query_comments(Comment.c.link_id == post._id, Comment.c.ob_imported == True)
        [self.process_comment(comment_data, comment, post, comment_dictionary)
         for comment_data, comment in map(None, post_data.get('comments', []), comments)]

    def substitute_ob_url(self, url):
        try:
            url = self.post_mapping[url].url
        except KeyError:
            pass
        return url

    # Borrowed from http://stackoverflow.com/questions/161738/what-is-the-best-regular-expression-to-check-if-a-string-is-a-valid-url/163684#163684
    url_re = re.compile(r"""(?:https?|ftp|file)://[-A-Z0-9+&@#/%?=~_|!:,.;]*[-A-Z0-9+&@#/%=~_|]""", re.IGNORECASE)
    def rewrite_ob_urls(self, text):
        if text:
            if isinstance(text, str):
                text = text.decode('utf-8')

            # Double decode needed to handle some wierd characters
            # text = text.encode('utf-8')
            text = self.url_re.sub(lambda match: self.substitute_ob_url(match.group()), text)

        return text

    def post_process_post(self, post):
        """Perform post processsing to rewrite URLs and generate mapping
           between old and new permalinks"""
        post.article = self.rewrite_ob_urls(post.article)
        post._commit()

        comments = Comment._query(Comment.c.link_id == post._id, data = True)
        for comment in comments:
            comment.body = self.rewrite_ob_urls(comment.body)
            comment._commit()

    def _post_process(self, rewrite_map_file):
        def unicode_safe(text):
            if isinstance(text, unicode):
                return text.encode('utf-8')
            else:
                return text

        posts = list(Link._query(Link.c.ob_permalink != None, data = True))

        # Generate a mapping between ob permalinks and imported posts
        self.post_mapping = {}
        for post in posts:
            self.post_mapping[post.ob_permalink] = post

        # Write out the rewrite map
        for old_url, post in self.post_mapping.iteritems():
            ob_url = urlparse.urlparse(old_url)
            new_url = post.canonical_url
            try:
                rewrite_map_file.write("%s %s\n" % (unicode_safe(ob_url.path), unicode_safe(new_url)))
            except UnicodeEncodeError, uee:
                print "Unable to write to rewrite map file:"
                print unicode_safe(ob_url.path)
                print unicode_safe(new_url)

        # Update URLs in the posts and comments
        print 'Post processing imported content'
        for post in posts:
            self.post_process_post(post)

    def import_into_subreddit(self, sr, data, rewrite_map_file):
        posts = list(Link._query())
        for post in posts:
            post._delete_from_db()

        comments = self._query_comments()
        for comment in comments:
            comment._delete_from_db()

        for post_data in data:
            try:
                print post_data['title']
                self.process_post(post_data, sr)
            except Exception, e:
                print 'Unable to create post:\n%s\n%s\n%s' % (type(e), e, post_data)
                raise

        self._post_process(rewrite_map_file)

    def _query_account(self, *args):
        account = None
        kwargs = {'data': True}
        q = Account._query(*args, **kwargs)
        accounts = list(q)
        if accounts:
            account = accounts[0]
        return account

    def _query_post(self, *args):
        post = None
        kwargs = {'data': True}
        q = Link._query(*args, **kwargs)
        posts = list(q)
        if posts:
            post = posts[0]
        return post

    def _query_comments(self, *args):
        kwargs = {'data': True}
        q = Comment._query(*args, **kwargs)
        comments = list(q)
        return comments

    def _username_from_name(self, name):
        """Convert a name into a username"""
        return name.replace(' ', '_')

    def _find_account_for(self, name, email):
        """Try to find an existing account using derivations of the name"""

        try:
            # Look for an account we have cached
            account = self.username_mapping[(name, email)]
        except KeyError:
            # Look for an existing account that was created due to a previous import
            account = self._query_account(Account.c.ob_account_name == name,
                                          Account.c.email == email)
            if not account:
                # Look for an existing account based on derivations of the name
                candidates = (
                    name,
                    name.replace(' ', ''),
                    self._username_from_name(name)
                )

                account = None
                for candidate in candidates:
                    account = self._query_account(Account.c.name == candidate,
                                                  Account.c.email == email)
                    if account:
                        account.ob_account_name = name
                        account._commit()
                        break

            # Cache the result for next time
            self.username_mapping[(name, email)] = account

        if not account:
            raise NotFound

        return account

    def _get_or_create_account(self, full_name, email):
        try:
            account = self._find_account_for(full_name, email)
        except NotFound:
            retry = 2 # First retry will by name2
            name = self._username_from_name(full_name)
            username = name
            while True:
                # Create a new account
                try:
                    account = register(username, generate_password(), email)
                    account.ob_account_name = full_name
                    account._commit()
                except AccountExists:
                    # This username is taken, generate another, but first limit the retries
                    if retry > MAX_RETRIES:
                        raise StandardError("Unable to create account for '%s' after %d attempts" % (full_name, retry - 1))
                else:
                    # update cache with the successful account
                    self.username_mapping[(full_name, email)] = account
                    break
                username = "%s%d" % (name, retry)
                retry += 1

        return account

