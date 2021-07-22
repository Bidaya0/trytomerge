#!/usr/bin/env python
# -*- coding:utf-8 -*-
# author:owefsad
# datetime:2020/11/30 下午3:13
# software: PyCharm
# project: lingzhi-webapi
import base64
import logging
import time

from dongtai.models.agent import IastAgent
from dongtai.models.project import IastProject
from dongtai.models.project_version import IastProjectVersion
from dongtai.models.server import IastServer
from rest_framework.request import Request

from dongtai.endpoint import OpenApiEndPoint, R
from apiserver.decrypter import parse_data

logger = logging.getLogger('dongtai.openapi')


class AgentRegisterEndPoint(OpenApiEndPoint):
    """
    引擎注册接口
    """
    name = "api-v1-agent-register"
    description = "引擎注册"

    @staticmethod
    def register_agent(token, version, language, project_name, user):
        project = IastProject.objects.values('id').filter(name=project_name, user=user).first()
        if project:
            project_current_version = IastProjectVersion.objects.filter(
                project_id=project['id'],
                current_version=1,
                status=1
            ).values("id").first()

            agent_id = AgentRegisterEndPoint.get_agent_id(token, project_name, user, project_current_version['id'])
            if agent_id == -1:
                agent_id = AgentRegisterEndPoint.__register_agent(
                    exist_project=True,
                    token=token,
                    user=user,
                    version=version,
                    project_id=project['id'],
                    project_name=project_name,
                    project_version_id=project_current_version['id'],
                    language=language,
                )
        else:
            agent_id = AgentRegisterEndPoint.get_agent_id(token=token, project_name=project_name, user=user,
                                                          current_project_version_id=0)
            if agent_id == -1:
                agent_id = AgentRegisterEndPoint.__register_agent(
                    exist_project=False,
                    token=token,
                    user=user,
                    version=version,
                    project_id=0,
                    project_name=project_name,
                    project_version_id=0,
                    language=language,
                )
        return agent_id

    @staticmethod
    def get_command(envs):
        for env in envs:
            if 'sun.java.command' in env.lower():
                return '='.join(env.split('=')[1:])
        return ''

    @staticmethod
    def get_runtime(envs):
        for env in envs:
            if 'java.runtime.name' in env.lower():
                return '='.join(env.split('=')[1:])
        return ''

    @staticmethod
    def register_server(agent_id, hostname, network, container_name, container_version, server_addr, server_port,
                        server_path, server_env, pid):
        """
        注册server，并关联server至agent
        :param agent_id:
        :param hostname:
        :param network:
        :param container_name:
        :param container_version:
        :param server_addr:
        :param server_port:
        :param server_path:
        :param server_env:
        :param pid:
        :return:
        """
        agent = IastAgent.objects.filter(id=agent_id).first()
        if agent is None:
            return
        # todo 需要根据不同的语言做兼容
        if server_env:
            env = base64.b64decode(server_env).decode('utf-8')
            env = env.replace('{', '').replace('}', '')
            envs = env.split(',')
            command = AgentRegisterEndPoint.get_command(envs)
        else:
            command = ''
            env = ''
            envs = []

        try:
            port = int(server_port)
        except Exception as e:
            logger.error(f'服务器端口不存在，已设置为默认值：0')
            port = 0

        server_id = agent.server_id

        server = IastServer.objects.filter(id=server_id).first() if server_id else None
        if server:
            server.hostname = hostname
            server.network = network
            server.command = command
            server.ip = server_addr
            server.port = port
            server.pid = pid
            server.env = env
            server.status = 'online'
            server.update_time = int(time.time())
            server.save(update_fields=['hostname', 'command', 'ip', 'port', 'environment', 'status', 'update_time'])
        else:
            server = IastServer.objects.create(
                hostname=hostname,
                ip=server_addr,
                port=port,
                pid=pid,
                network=network,
                env=env,
                path=server_path,
                status='online',
                container=container_name,
                container_path=server_path,
                command=command,
                runtime=AgentRegisterEndPoint.get_runtime(envs),
                create_time=int(time.time()),
                update_time=int(time.time())
            )
            agent.server_id = server.id
            agent.save(update_fields=['server_id'])
            logger.info(f'服务器记录创建成功')

    def post(self, request: Request):
        """
        IAST下载 agent接口s
        :param request:
        :return:
        服务器作为agent的唯一值绑定
        token: agent-ip-port-path
        """
        # 接受 token名称，version，校验token重复性，latest_time = now.time()
        # 生成agent的唯一token
        # 注册
        try:
            param = parse_data(request.read())
            token = param.get('name')
            language = param.get('language')
            version = param.get('version')
            project_name = param.get('project_name', 'Demo Project').strip()
            if not token or not version or not project_name:
                return R.failure(msg="参数错误")

            hostname = param.get('hostname')
            network = param.get('network')
            container_name = param.get('container_name')
            container_version = param.get('container_version')
            server_addr = param.get('web_server_addr')
            server_port = param.get('web_server_port')
            server_path = param.get('web_server_path')
            server_env = param.get('server_env')
            pid = param.get('pid')

            user = request.user
            agent_id = self.register_agent(
                token=token,
                version=version,
                project_name=project_name,
                language=language,
                user=user
            )

            self.register_server(
                agent_id=agent_id,
                hostname=hostname,
                network=network,
                container_name=container_name,
                container_version=container_version,
                server_addr=server_addr,
                server_port=server_port,
                server_path=server_path,
                server_env=server_env,
                pid=pid,
            )

            return R.success(data={'id': agent_id})
        except Exception as e:
            return R.failure(msg="探针注册失败，原因：{reason}".format(reason=e))

    @staticmethod
    def get_agent_id(token, project_name, user, current_project_version_id):
        queryset = IastAgent.objects.values('id').filter(
            token=token,
            project_name=project_name,
            user=user,
            project_version_id=current_project_version_id
        )
        agent = queryset.first()
        if agent:
            queryset.update(is_core_running=1)
            return agent['id']
        return -1

    @staticmethod
    def __register_agent(exist_project, token, user, version, project_id, project_name, project_version_id, language):
        if exist_project:
            IastAgent.objects.filter(token=token, online=1, user=user).update(online=0)

        agent = IastAgent.objects.create(
            token=token,
            version=version,
            latest_time=int(time.time()),
            user=user,
            is_running=1,
            bind_project_id=project_id,
            project_name=project_name,
            control=0,
            is_control=0,
            is_core_running=1,
            online=1,
            project_version_id=project_version_id,
            language=language
        )
        return agent.id
