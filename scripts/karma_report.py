import code
from r2.config import databases
from sqlalchemy.sql import text

# These functions will fail badly if the databases (main, comment,
# vote) are ever split.

def list_voters(user):
    sql = '''
SELECT
  voter.value,
  SUM(vote.name::integer) AS votes
FROM
  reddit_rel_vote_account_comment AS vote
  INNER JOIN reddit_data_account AS voter ON voter.thing_id = vote.thing1_id
  INNER JOIN reddit_data_comment AS comment ON comment.thing_id = vote.thing2_id
WHERE
  voter.key = 'name' AND
  comment.key = 'author_id' AND
  comment.value = (SELECT thing_id
                   FROM reddit_data_account
                   WHERE key = 'name' AND value = :user)::text
GROUP BY
  voter.value
ORDER BY
  votes ASC
'''
    res = databases.main_engine.execute(text(sql), user=user)
    for row in res:
        print(row[0], row[1])

def num_comments(user):
    sql = '''
SELECT
  COUNT(*)
FROM
  reddit_data_comment AS comment
WHERE
  comment.key = 'author_id' AND
  comment.value = (SELECT thing_id
                   FROM reddit_data_account
                   WHERE key = 'name' AND value = :user)::text
'''
    res = databases.main_engine.execute(text(sql), user=user)
    for row in res:
        print row[0]

def count_replies(author, replier):
    sql = '''
SELECT
  COUNT(*)
FROM
  reddit_data_comment AS comment
WHERE
  comment.key = 'author_id' AND
  comment.value = (SELECT thing_id
                   FROM reddit_data_account
                   WHERE key = 'name' AND value = :replier)::text AND
  comment.thing_id IN (-- thing_ids of replies to comment in set
                       SELECT
                         thing_id::integer
                       FROM
                         reddit_data_comment AS comment
                       WHERE
                         comment.key = 'parent_id' AND
                         comment.value IN (-- thing_id of author's comments
                                           SELECT
                                             thing_id::text
                                           FROM
                                             reddit_data_comment AS comment
                                           WHERE
                                             comment.key = 'author_id' AND
                                             comment.value = (SELECT thing_id
                                                              FROM reddit_data_account
                                                              WHERE key = 'name' AND value = :author)::text))
'''
    res = databases.main_engine.execute(text(sql), author=author, replier=replier)
    for row in res:
        print row[0]

code.interact(local=locals())
