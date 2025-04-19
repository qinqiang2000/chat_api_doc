import time
import logging
import traceback
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from openai import OpenAI, NotFoundError
from openai.types.beta.threads import Run

# Configure logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# Create console handler with a higher log level
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)

# Create formatter and add it to the handlers
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
ch.setFormatter(formatter)

# Add the handlers to the logger
logger.addHandler(ch)

# Assistant类，用于处理openai的对话请求
class Assistant():
    def __init__(self, assistant_id: str, client: OpenAI):
        self.assistant_id = assistant_id
        self.client = client
        self.topic = assistant_id + "_vector_store"

    def get_vector_store_ids(self):
        vector_store = []
        try:
            my_assistant = self.client.beta.assistants.retrieve(self.assistant_id)
            file_search = my_assistant.tool_resources.file_search
            if file_search is None:
                logger.error(f"[asst_id={self.assistant_id}]：assistant没有启用file_search工具")
                return vector_store
            vector_store = my_assistant.tool_resources.file_search.vector_store_ids
        except Exception as e:
            logger.error(f"[asst_id={self.assistant_id}]：获取vector store失败：{e}")
        return vector_store
    
    def delete_vector_store_file(self, vector_store_id: str, file_id: str) -> bool:
        """
        删除向量库中的文件
        :param vector_store_id (str): 向量库 ID
        :param file_id (str): 文件 ID
        :return bool: 是否删除成功
        """
        try:
            deleted_file = self.client.vector_stores.files.delete(
                vector_store_id=vector_store_id, file_id=file_id
            )
            if deleted_file.deleted:
                logger.debug(f"[asst_id={self.assistant_id}]：在 OpenAI 向量库 '{vector_store_id}' 中删除文件成功: {deleted_file}")
                return True
            logger.error(f"[asst_id={self.assistant_id}]：在 OpenAI 向量库 '{vector_store_id}' 中删除文件失败: {deleted_file}")
            return False
        except NotFoundError:
            logger.info(f"[asst_id={self.assistant_id}]：OpenAI 向量库 '{vector_store_id}'中不存在 '{file_id}' 文件, 已跳过删除")
            return True
        except Exception as e:
            logger.error(f"[asst_id={self.assistant_id}]：删除 OpenAI 向量库 '{vector_store_id}' 文件 '{file_id}' 失败: {e}")
            return False

    def delete_openai_file(self, file_id: str) -> bool:
        """
        删除 OpenAI 文件
        :param client (openai.Client): OpenAI 客户端实例
        :param file_id (str): 文件 ID
        :return bool: 是否删除成功
        """
        try:
            deleted_file = self.client.files.delete(file_id)
            if deleted_file.deleted:
                logger.debug(f"[asst_id={self.assistant_id}]：在 OpenAI 文件中删除文件成功: {deleted_file}")
                return True
            logger.error(f"[asst_id={self.assistant_id}]：在 OpenAI 文件中删除文件失败: {deleted_file}")
            return False
        except NotFoundError:
            logger.info(f"[asst_id={self.assistant_id}]：OpenAI 文件 '{file_id}' 不存在, 已跳过删除")
            return True
        except Exception as e:
            logger.error(f"[asst_id={self.assistant_id}]：删除 OpenAI 文件 '{file_id}' 失败: {e}")
            return False

    def empty_files(self) -> bool:
        """
        清空assistant的文件
        :return: 是否清空了文件
        """
        try:
            vector_store_ids = self.get_vector_store_ids()
            if not vector_store_ids:
                logger.info(f"[asst_id={self.assistant_id}]：助手没有关联的向量库")
                return True
            # 删除第一个向量库之外的所有向量库
            if len(vector_store_ids) > 1:
                for vector_store_id in vector_store_ids[1:]:
                    deleted_vector_store = self.client.vector_stores.delete(vector_store_id=vector_store_id)
                    if not deleted_vector_store.deleted:
                        logger.error(
                            f"[asst_id={self.assistant_id}]：删除向量库 '{deleted_vector_store.id}' 失败, 请后续手动删除并重新同步数据"
                        )
                    else:
                        logger.info(f"[asst_id={self.assistant_id}]: 已删除向量库 '{deleted_vector_store.id}'")

            vector_store_id = vector_store_ids[0]

            # 获取向量库下的文件
            vector_store_files = []
            after = None
            limit = 100
            while True:
                response = self.client.vector_stores.files.list(
                    vector_store_id=vector_store_id,
                    limit=limit,
                    after=after
                )
                vector_store_files.extend(response.data)
                if len(response.data) < limit:
                    break
                after = response.data[-1].id


            is_processing_files = any(
                file.status == "in_progress" for file in vector_store_files
            )
            failed_vector_store_files = []
            failed_openai_files = []

            # 删除向量库和 OpenAI 文件
            for file in vector_store_files:
                vector_store_deleted = self.delete_vector_store_file(
                    vector_store_id, file.id
                )
                if not vector_store_deleted:
                    failed_vector_store_files.append(file.id)

                openai_deleted = self.delete_openai_file(file.id)
                if not openai_deleted:
                    failed_openai_files.append(file.id)
            # 查看向量库是否过期
            check_status_vector_store = self.client.vector_stores.retrieve(
                vector_store_id=vector_store_id
            )
            is_expired = check_status_vector_store.status =="expired"
            if not is_expired:
                # 更新向量库名称
                self.client.vector_stores.update(
                    vector_store_id=vector_store_id,
                    name=self.topic,
                    expires_after={
                        "anchor": "last_active_at",
                        "days": 30
                    }
                )

            success_count = len(vector_store_files) - len(failed_vector_store_files) #成功删除的文件数量

            # 删除整个向量库
            if is_processing_files or failed_vector_store_files or failed_openai_files or is_expired:
                logger.info(
                    f"[asst_id={self.assistant_id}]：向量库 '{vector_store_id}' 下的部分文件正在处理中或无法正常删除, 强制删除整个向量库"
                )
                deleted_vector_store = self.client.vector_stores.delete(
                    vector_store_id=vector_store_id
                )
                if not deleted_vector_store.deleted:
                    logger.error(
                        f"[asst_id={self.assistant_id}]：删除向量库 '{deleted_vector_store.id}' 失败, 请后续手动删除并重新同步数据"
                    )
                else:
                    success_count = len(vector_store_files)

            logger.info(
                f"[asst_id={self.assistant_id}]：已清空助手的文件: {success_count}/{len(vector_store_files)}"
            )
            return True
        except Exception as e:
            logger.error(f"[asst_id={self.assistant_id}]：清空助手文件失败：{e}\n{traceback.format_exc()}")
            return False



    def create_vs(self,file_paths_and_urls: list) -> bool:
        """
        创建向量库并上传文件
        :param file_paths: url和文件路径
        :return: 是否上传成功
        """
        vector_store_ids = self.get_vector_store_ids()
        if not vector_store_ids:
            vector_store = self.client.vector_stores.create(
                name=self.topic,
                expires_after={
                    "anchor": "last_active_at",
                    "days": 7
                })
            vector_store_ids = [vector_store.id]
            assistant = self.client.beta.assistants.update(
                assistant_id=self.assistant_id,
                tool_resources={"file_search": {"vector_store_ids": vector_store_ids}},
            )
        elif len(vector_store_ids) > 1:
            assistant = self.client.beta.assistants.update(
                assistant_id=self.assistant_id,
                tool_resources={"file_search": {"vector_store_ids": [vector_store_ids[0]]}},
            )
        return self.upload_file(file_paths_and_urls,vector_store_ids[0])

    def _upload_single_file(self, path):
        with open(path, "rb") as file:
            return self.client.files.create(file=file, purpose="assistants")


    def upload_file(self, file_paths_and_urls: list, vector_store_id: str) -> bool:
        MAX_RETRIES = 3
        BATCH_SIZE = 100
        MAX_CONCURRENCY = 5
        logger.debug(f"[asst_id={self.assistant_id}]：上传{len(file_paths_and_urls)}个文件到向量库 '{vector_store_id}'")

        # 1.上传 files
        results = []
        with ThreadPoolExecutor(max_workers=MAX_CONCURRENCY) as executor:
            futures = {
                executor.submit(
                    self._upload_single_file,
                    path=path,
                ): url
                for url, path in file_paths_and_urls
            }

        for future in as_completed(futures):
            url = futures[future]
            exc = future.exception()
            if exc:
                raise exc
            results.append((url, future.result()))

        # 2.将 file_id 和url的对应关系储存在数据库中

        # 3.将files添加到vector store，带重试逻辑,只有上传失败的情况下会重试
        file_ids = [f.id for _, f in results]
        total_files = len(file_ids)
        retry_count = 0
        successful_files = 0
        while retry_count < MAX_RETRIES and len(file_ids):
            ## 3.1 批量上传文件
            failed_file_ids = []
            for i in range(0, len(file_ids), BATCH_SIZE):
                batch = file_ids[i:i + BATCH_SIZE]
                file_batch = self.client.vector_stores.file_batches.create_and_poll(
                    vector_store_id=vector_store_id,
                    file_ids=batch
                    # chunking_strategy=chunking_strategy
                )

                if file_batch.status == "completed":
                    successful_files += file_batch.file_counts.completed
                    logger.info(
                        f"[asst_id={self.assistant_id}]：成功上传第 {i // BATCH_SIZE + 1} 批文件：{file_batch.file_counts}"
                    )
                else:
                    logger.error(
                        f"[asst_id={self.assistant_id}]：第 {i // BATCH_SIZE + 1} 批文件上传失败，文件上传终止，状态 '{file_batch.status}'：{file_batch.file_counts}")
                    return False

            logger.info(
                f"[asst_id={self.assistant_id}]：当前重试次数 {retry_count + 1}，成功上传{successful_files}/{total_files}"
            )
            # 3.2 获取上传失败的文件
            try:
                # 获取这个批次中失败的文件ID
                after = None
                limit = 100
                while True:
                    response = self.client.vector_stores.files.list(
                        vector_store_id=vector_store_id,
                        filter="failed",
                        limit=limit,
                        after=after
                    )
                    failed_file_ids.extend([file_ins.id for file_ins in response.data])
                    if len(response.data) < limit:
                        break
                    after = response.data[-1].id
            except Exception as e:
                logger.error(f"[asst_id={self.assistant_id}]： 获取失败文件列表时发生异常：{e}")


            if not failed_file_ids and successful_files == total_files:
                logger.info(f"[asst_id={self.assistant_id}]：所有文件上传成功")
                return True

            # 如果还有失败的文件且未达到最大重试次数，则清理失败的文件并准备重试
            if retry_count < MAX_RETRIES - 1:
                logger.info(
                    f"[asst_id={self.assistant_id}]：{total_files-successful_files}个文件上传失败，准备第{retry_count + 2}次重试"
                )
                # 删除向量库中失败的文件
                for failed_id in failed_file_ids:
                    self.delete_vector_store_file(vector_store_id, failed_id)

                # 更新file_ids为失败的文件列表，准备重试
                file_ids = failed_file_ids
                retry_count += 1
            else:
                logger.error(
                    f"[asst_id={self.assistant_id}]：达到最大重试次数，{total_files-successful_files}个文件上传失败，请稍后重试"
                )
                return False

        return False

