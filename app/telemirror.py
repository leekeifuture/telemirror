import asyncio
import logging
import time

from telethon import events
from telethon.sessions import StringSession
from telethon.sync import TelegramClient
from telethon.tl.types import \
    InputMediaPoll, \
    MessageMediaPoll, \
    MessageEntityTextUrl

from database import Database, MirrorMessage
from settings import (API_HASH, API_ID, DB_URL,
                      LIMIT_TO_WAIT, LOG_LEVEL, SESSION_STRING,
                      TIMEOUT_MIRRORING, TARGET)
from utils import remove_urls

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(level=LOG_LEVEL)

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
db = Database(DB_URL)

not_muted_chats = []


def remove_url_from_message(message):
    message.message = remove_urls(message.message)
    if message.entities is not None:
        for e in message.entities:
            if isinstance(e, MessageEntityTextUrl):
                e.url = remove_urls(e.url)
    return message


async def update_not_muted_chats():
    dialogs = await client.get_dialogs()

    tmp = []
    for dialog in dialogs:
        if (dialog.dialog.notify_settings.mute_until is None or
                dialog.dialog.notify_settings.mute_until.year == 1970):
            tmp.append(dialog.entity.id)

    global not_muted_chats
    not_muted_chats = tmp


async def check_not_muted_chats():
    while True:
        await update_not_muted_chats()
        await asyncio.sleep(10)


@client.on(events.Album(func=lambda e: e.chat_id in not_muted_chats))
async def handler_album(event):
    """Album event handler.
    """
    try:
        logger.debug(f'New Album from {event.chat_id}:\n{event}')

        if TARGET is None:
            logger.warning(
                f'Album. No target channel for {event.chat_id}'
            )
            return
        # media
        files = []
        # captions
        caps = []
        # original messages ids
        original_idxs = []
        for item in event.messages:
            files.append(item.media)
            caps.append(item.message)
            original_idxs.append(item.id)
        sent = 0

        mirror_messages = await client.send_file(TARGET, caption=caps,
                                                 file=files)
        if mirror_messages is not None and len(mirror_messages) > 1:
            for idx, m in enumerate(mirror_messages):
                db.insert(MirrorMessage(original_id=original_idxs[idx],
                                        original_channel=event.chat_id,
                                        mirror_id=m.id,
                                        mirror_channel=TARGET))
        sent += 1
        if sent > LIMIT_TO_WAIT:
            sent = 0
            time.sleep(TIMEOUT_MIRRORING)

    except Exception as e:
        logger.error(e, exc_info=True)


@client.on(events.NewMessage(func=lambda e: e.chat_id in not_muted_chats))
async def handler_new_message(event):
    """NewMessage event handler.
    """
    # skip if Album
    if hasattr(event, 'grouped_id') and event.grouped_id is not None:
        return

    try:
        logger.debug(f'New message from {event.chat_id}:\n{event.message}')

        if TARGET is None:
            logger.warning(
                f'NewMessage. No target channel for {event.chat_id}'
            )
            return

        sent = 0

        if isinstance(event.message.media, MessageMediaPoll):
            mirror_message = await client.forward_messages(
                TARGET, file=InputMediaPoll(poll=event.message.media.poll)
            )
        else:
            mirror_message = await client.forward_messages(TARGET,
                                                           event.message)

        if mirror_message is not None:
            db.insert(MirrorMessage(original_id=event.message.id,
                                    original_channel=event.chat_id,
                                    mirror_id=mirror_message.id,
                                    mirror_channel=TARGET))
        sent += 1
        if sent > LIMIT_TO_WAIT:
            sent = 0
            time.sleep(TIMEOUT_MIRRORING)

    except Exception as e:
        logger.error(e, exc_info=True)


@client.on(events.MessageEdited(func=lambda e: e.chat_id in not_muted_chats))
async def handler_edit_message(event):
    """MessageEdited event handler.
    """
    try:
        logger.debug(f'Edit message {event.message.id} from {event.chat_id}')
        targets = db.find_by_original_id(event.message.id, event.chat_id)
        if targets is None or len(targets) < 1:
            logger.warning(
                f'MessageEdited. No target channel for {event.chat_id}'
            )
            return

        sent = 0
        for chat in targets:
            await client.forward_messages(chat.mirror_channel, event.message)
            sent += 1
            if sent > LIMIT_TO_WAIT:
                sent = 0
                time.sleep(TIMEOUT_MIRRORING)
    except Exception as e:
        logger.error(e, exc_info=True)


async def main():
    await client.start()
    if await client.is_user_authorized():
        me = await client.get_me()
        logger.info(f'Connected as {me.username} ({me.phone})')

        await asyncio.gather(
            check_not_muted_chats(),
            client.run_until_disconnected()
        )
    else:
        logger.error('Cannot be authorized')


if __name__ == '__main__':
    loop = asyncio.get_event_loop().run_until_complete(main())
