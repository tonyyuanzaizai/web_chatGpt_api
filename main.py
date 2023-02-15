import asyncio
import uuid
import openai
from threading import Timer
from urllib import parse

import socketio
from aiohttp import web

# Initialize the OpenAI API client
openai.api_key = "your key"

user_uuid_set, using_uuid_set, logout_uuid_set, token_set, using_email_set = set(
), set(), set(), set(), set()
timer_map, sid_uuid_map, token_email_map, email_chat_map, user_token_map = {}, {}, {}, {}, {}

account_list_len = 10  # 访问人数限制

sio = socketio.AsyncServer(cors_allowed_origins='*')
app = web.Application()

sio.attach(app)


def logout(userUUID):
    if userUUID in logout_uuid_set:
        if userUUID in user_uuid_set: user_uuid_set.remove(userUUID)
        if userUUID in using_uuid_set: using_uuid_set.remove(userUUID)
        logout_uuid_set.remove(userUUID)
        try:
            token = user_token_map[userUUID]
            email = token_email_map[token]
            token_set.remove(token)
            using_email_set.remove(email)
            del user_token_map[userUUID]
            del timer_map[userUUID]
            asyncio.run(broadcastSystemInfo())
        except Exception as e:
            print(e)


# Define a function to generate a response based on the current context
def ask(context):
    model_engine = "text-davinci-003"
    prompt = context
    completions = openai.Completion.create(
        engine=model_engine,
        prompt=prompt,
        max_tokens=2048,
        n=1,
        stop=None,
        temperature=0.5,
    )
    print(completions)
    message = completions.choices[0].text
    return  message


async def broadcastSystemInfo():
    onlineUserNum = len(user_uuid_set)
    waitingUserNum = onlineUserNum - len(using_uuid_set)
    await sio.emit(
        'systemInfo', {
            'onlineUserNum': onlineUserNum if onlineUserNum > 1 else 1,
            'waitingUserNum': waitingUserNum if waitingUserNum > 0 else 0,
            'accountCount': account_list_len
        })


async def rushHandler(sid, userUUID):
    if len(using_uuid_set) < account_list_len:  # System simultaneous load number
        token = str(uuid.uuid4())
        token_set.add(token)
        user_token_map[userUUID] = token
        userUUID = sid_uuid_map.get(sid)
        using_uuid_set.add(userUUID)
        await sio.emit('token', token, room=sid)
        return
    await sio.emit('restricted', room=sid)


def getAnswer(sid, text, token):
    try:
        print("You: " + text)
        email = token_email_map.get(token)
        # Generate a response
        answer = ask(text)
        print(answer)

        if answer:
            print("AI: " + answer)
            asyncio.run(sio.emit('answer', {
                'code': 1,
                'result': answer
            }, room=sid))
        else:
            asyncio.run(sio.emit('answer', {
                'code': -2,
                'result': '网络错误'
            }, room=sid))
    except Exception as err:
        print('repr(err):\t', repr(err))
        asyncio.run(sio.emit('answer', {
            'code': -1,
            'msg': str(err)
        }, room=sid))


@sio.event
async def connect(sid, environ):
    queryDict = parse.parse_qs(environ['QUERY_STRING'])
    if 'userUUID' in queryDict.keys() and queryDict['userUUID'][0]:
        userUUID = queryDict['userUUID'][0]
        sid_uuid_map[sid] = userUUID
        if userUUID in logout_uuid_set:
            logout_uuid_set.remove(userUUID)
            try:
                timer_map[userUUID].cancel()
                del timer_map[userUUID]
            except:
                pass
        user_uuid_set.add(userUUID)
        print("connect ", userUUID)


@sio.event
async def rush(sid, data):
    userUUID = sid_uuid_map.get(sid)
    await rushHandler(sid, userUUID)


@sio.event
async def ready(sid, data):
    userUUID = sid_uuid_map.get(sid)
    if userUUID not in using_uuid_set: await rushHandler(sid, userUUID)
    await broadcastSystemInfo()


@sio.event
def disconnect(sid):
    userUUID = sid_uuid_map[sid]
    logout_uuid_set.add(userUUID)
    timer_map[userUUID] = Timer(3, logout, (userUUID,))
    timer_map[userUUID].start()
    del sid_uuid_map[sid]
    print('disconnect uuid:', userUUID)


@sio.event
async def chatgpt(sid, data):
    text = data.get('text')
    token = data.get('token')
    task = Timer(3, getAnswer, (
        sid,
        text,
        token,
    ))

    task.start()


async def index(request):
    return web.json_response({'error': -1})


app.router.add_get('/', index)

if __name__ == '__main__':
    web.run_app(app, host="0.0.0.0", port=50000)
