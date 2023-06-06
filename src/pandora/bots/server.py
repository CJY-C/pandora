# -*- coding: utf-8 -*-

import logging
from datetime import timedelta
from os.path import join, abspath, dirname

from flask import Flask, jsonify, make_response, request, Response, render_template,stream_with_context
from flask_cors import CORS
from waitress import serve
from werkzeug.exceptions import default_exceptions
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.serving import WSGIRequestHandler

from .. import __version__
from ..exts.hooks import hook_logging
from ..openai.api import API
import uuid
import json


class ChatBot:
    __default_ip = '127.0.0.1'
    __default_port = 8008

    def __init__(self, chatgpt, debug=False, sentry=False):
        self.chatgpt = chatgpt
        self._app = None
        self.debug = debug
        self.sentry = sentry
        self.log_level = logging.DEBUG if debug else logging.WARN

        hook_logging(level=self.log_level, format='[%(asctime)s] %(levelname)s in %(module)s: %(message)s')
        self.logger = logging.getLogger('waitress')

    def run(self, bind_str, threads=8):
        host, port = self.__parse_bind(bind_str)

        resource_path = abspath(join(dirname(__file__), '..', 'flask'))
        app = Flask(__name__, static_url_path='',
                    static_folder=join(resource_path, 'static'),
                    template_folder=join(resource_path, 'templates'))
        app.wsgi_app = ProxyFix(app.wsgi_app, x_port=1)
        app.after_request(self.__after_request)

        CORS(app, resources={r'/api/*': {'supports_credentials': True, 'expose_headers': [
            'Content-Type',
            'Authorization',
            'X-Requested-With',
            'Accept',
            'Origin',
            'Access-Control-Request-Method',
            'Access-Control-Request-Headers',
            'Content-Disposition',
        ], 'max_age': 600}})

        for ex in default_exceptions:
            app.register_error_handler(ex, self.__handle_error)

        app.route('/api/models')(self.list_models)
        app.route('/api/conversations')(self.list_conversations)
        app.route('/api/conversations', methods=['DELETE'])(self.clear_conversations)
        app.route('/api/conversation/<conversation_id>')(self.get_conversation)
        app.route('/api/conversation/<conversation_id>', methods=['DELETE'])(self.del_conversation)
        app.route('/api/conversation/<conversation_id>', methods=['PATCH'])(self.set_conversation_title)
        app.route('/api/conversation/gen_title/<conversation_id>', methods=['POST'])(self.gen_conversation_title)
        app.route('/api/conversation/talk', methods=['POST'])(self.talk)
        app.route('/api/conversation/regenerate', methods=['POST'])(self.regenerate)
        app.route('/api/conversation/goon', methods=['POST'])(self.goon)

        app.route('/api/auth/session')(self.session)
        app.route('/api/accounts/check')(self.check)
        app.route('/_next/data/olf4sv64FWIcQ_zCGl90t/chat.json')(self.chat_info)

        app.route('/')(self.chat_demo)
        app.route('/chat')(self.chat)
        app.route('/voice')(self.voice)
        
        app.route('/chat/<conversation_id>')(self.chat)
        
        app.route('/v1/chat/completions', methods=['POST'])(self._openai2)
        
        
        self._app = app
        

        if not self.debug:
            self.logger.warning('Serving on http://{}:{}'.format(host, port))

        WSGIRequestHandler.protocol_version = 'HTTP/1.1'
        serve(app, host=host, port=port, ident=None, threads=threads)

    @staticmethod
    def __after_request(resp):
        resp.headers['X-Server'] = 'pandora/{}'.format(__version__)

        return resp

    def __parse_bind(self, bind_str):
        sections = bind_str.split(':', 2)
        if len(sections) < 2:
            try:
                port = int(sections[0])
                return self.__default_ip, port
            except ValueError:
                return sections[0], self.__default_port

        return sections[0], int(sections[1])

    def __handle_error(self, e):
        self.logger.error(e)

        return make_response(jsonify({
            'code': e.code,
            'message': str(e.original_exception if self.debug and hasattr(e, 'original_exception') else e.name)
        }), 500)

    @staticmethod
    def __set_cookie(resp, token_key, max_age):
        resp.set_cookie('token-key', token_key, max_age=max_age, path='/', domain=None, httponly=True, samesite='Lax')

    @staticmethod
    def __get_token_key():
        return request.headers.get('X-Use-Token', request.cookies.get('token-key'))

    def chat(self, conversation_id=None):
        query = {'chatId': [conversation_id]} if conversation_id else {}

        token_key = request.args.get('token')
        rendered = render_template('chat.html',
                                   pandora_base=request.url_root.strip('/'),
                                   pandora_sentry=self.sentry,
                                   query=query
                                   )
        resp = make_response(rendered)

        if token_key:
            self.__set_cookie(resp, token_key, timedelta(days=30))

        return resp
    def voice(self):
        # +语音     https://github.com/possible318/pandora/tree/voice2text
         rendered = render_template('voice.html',
                                   pandora_base=request.url_root.strip('/'),
                                   pandora_sentry=self.sentry
                                   )
        resp = make_response(rendered)
        return resp
    
    
    def chat_demo(self):
        # 换个界面  https://github.com/xqdoo00o/chatgpt-web
        rendered = render_template('chatgpt-web.html',
                                   pandora_base=request.url_root.strip('/'),
                                   pandora_sentry=self.sentry
                                   )
        resp = make_response(rendered)
        return resp
    


    @staticmethod
    def session():
        ret = {
            'user': {
                'id': 'user-000000000000000000000000',
                'name': 'admin@openai.com',
                'email': 'admin@openai.com',
                'image': None,
                'picture': None,
                'groups': []
            },
            'expires': '2089-08-08T23:59:59.999Z',
            'accessToken': 'secret',
        }

        return jsonify(ret)

    @staticmethod
    def chat_info():
        ret = {
            'pageProps': {
                'user': {
                    'id': 'user-000000000000000000000000',
                    'name': 'admin@openai.com',
                    'email': 'admin@openai.com',
                    'image': None,
                    'picture': None,
                    'groups': []
                },
                'serviceStatus': {},
                'userCountry': 'US',
                'geoOk': True,
                'serviceAnnouncement': {
                    'paid': {},
                    'public': {}
                },
                'isUserInCanPayGroup': True
            },
            '__N_SSP': True
        }

        return jsonify(ret)

    @staticmethod
    def check():
        ret = {
            'account_plan': {
                'is_paid_subscription_active': True,
                'subscription_plan': 'chatgptplusplan',
                'account_user_role': 'account-owner',
                'was_paid_customer': True,
                'has_customer_object': True,
                'subscription_expires_at_timestamp': 3774355199
            },
            'user_country': 'US',
            'features': [
                'model_switcher',
                'dfw_message_feedback',
                'dfw_inline_message_regen_comparison',
                'model_preview',
                'system_message',
                'can_continue',
            ],
        }

        return jsonify(ret)

    def list_models(self):
        return self.__proxy_result(self.chatgpt.list_models(True, self.__get_token_key()))

    def list_conversations(self):
        offset = request.args.get('offset', '0')
        limit = request.args.get('limit', '20')

        return self.__proxy_result(self.chatgpt.list_conversations(offset, limit, True, self.__get_token_key()))

    def get_conversation(self, conversation_id):
        return self.__proxy_result(self.chatgpt.get_conversation(conversation_id, True, self.__get_token_key()))

    def del_conversation(self, conversation_id):
        return self.__proxy_result(self.chatgpt.del_conversation(conversation_id, True, self.__get_token_key()))

    def clear_conversations(self):
        return self.__proxy_result(self.chatgpt.clear_conversations(True, self.__get_token_key()))

    def set_conversation_title(self, conversation_id):
        title = request.json['title']

        return self.__proxy_result(
            self.chatgpt.set_conversation_title(conversation_id, title, True, self.__get_token_key()))

    def gen_conversation_title(self, conversation_id):
        payload = request.json
        model = payload['model']
        message_id = payload['message_id']

        return self.__proxy_result(
            self.chatgpt.gen_conversation_title(conversation_id, model, message_id, True, self.__get_token_key()))

    def talk(self):
        payload = request.json
        prompt = payload['prompt']
        model = payload['model']
        message_id = payload['message_id']
        parent_message_id = payload['parent_message_id']
        conversation_id = payload.get('conversation_id')
        stream = payload.get('stream', True)

        return self.__process_stream(
            *self.chatgpt.talk(prompt, model, message_id, parent_message_id, conversation_id, stream,
                               self.__get_token_key()), stream)

    def goon(self):
        payload = request.json
        model = payload['model']
        parent_message_id = payload['parent_message_id']
        conversation_id = payload.get('conversation_id')
        stream = payload.get('stream', True)

        return self.__process_stream(
            *self.chatgpt.goon(model, parent_message_id, conversation_id, stream, self.__get_token_key()), stream)

    def regenerate(self):
        payload = request.json

        conversation_id = payload.get('conversation_id')
        if not conversation_id:
            return self.talk()

        prompt = payload['prompt']
        model = payload['model']
        message_id = payload['message_id']
        parent_message_id = payload['parent_message_id']
        stream = payload.get('stream', True)

        return self.__process_stream(
            *self.chatgpt.regenerate_reply(prompt, model, conversation_id, message_id, parent_message_id, stream,
                                           self.__get_token_key()), stream)

    @staticmethod
    def __process_stream(status, headers, generator, stream):
        if stream:
            return Response(API.wrap_stream_out(generator, status), mimetype=headers['Content-Type'], status=status)

        last_json = None
        for json in generator:
            last_json = json

        return make_response(last_json, status)

    @staticmethod
    def __proxy_result(remote_resp):
        resp = make_response(remote_resp.text)
        resp.content_type = remote_resp.headers['Content-Type']
        resp.status_code = remote_resp.status_code

        return resp



    def _openai2(self):
        def generate(res):
            # res 文本回复, 本函数是转流格式回复
            for xx in res:
                x2x_json = {"choices":[{"delta":{"content":xx}}]}
                x3x_str = json.dumps(x2x_json)
                x4x_str = f"data: {x3x_str}\n\n"
                x5x_byte = x4x_str.encode('utf-8')
                yield x5x_byte

        messages = request.json.get("messages",'')
        #print(messages) # chatgpt应用端发送的 消息，含历史上下文和问题。

        txt = '' #整理后的上下文和问题
        for i in messages:
            txt = txt + f"{i.get('role')}:{i.get('content')}\n\n"
        with self._app.app_context():
            #res = self._open_ask(txt,False) # 不自动删除网页产生并显示的会话
            res = self._open_ask(txt) # 自动删除网页产生并显示的会话
            return Response(stream_with_context(generate(res)),mimetype='text/event-stream') # 原始全文字符串回复转为stream 格式返回给应用

    def _open_ask(self,txt,del_talk = True,model='text-davinci-002-render-sha'):
        # text-davinci-002-render-sha 似乎就是GPT3.5
        prompt = txt
        message_id = str(uuid.uuid4())
        parent_message_id = str(uuid.uuid4())
        conversation_id = None
        stream = False  #流请求，返回的格式不符合应用端使用。到'官方'不用流，到应用端用流。

        req = self.__process_stream(
            *self.chatgpt.talk(prompt, model, message_id, parent_message_id, conversation_id, stream,
                               self.__get_token_key()), stream)
        res = json.loads(req.get_data())
        #print(res)
        conversation_id = res.get('conversation_id')
        res_content = res.get('message').get('content').get('parts')[0]
        if res_content.startswith('assistant:'):
            res_content = res_content[10:] #不要开头的assistant:部分文字
        if del_talk:
            self.del_conversation(conversation_id)
        return res_content #单次完整全文回复
        
