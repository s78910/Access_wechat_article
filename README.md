## 微信文章获取（Access_wechat_article）

本项目是基于Python语言的爬虫程序，支持对微信公众号文章内容获取

目前支持 Windows / Linux 开箱即用，**建议使用虚拟环境运行项目**

如果感兴趣，请复制项目后自行研究使用

使用过程中如遇到错误，请提交[issues](https://github.com/yeximm/Access_wechat_article/issues)。

## 一、主要功能

1. 获取**公众号主页链接**，通过微信内置浏览器可直接打开
2. 获取公众号**已发布**的文章列表（**微信公众号**下的历史文章）
3. 批量下载公众号文章的**网页文本数据**
4. 获取微信公众号文章的**所有信息**，如阅读量、点赞数、转发数、评论、评论点赞等信息。

## 二、项目所需环境及工具

1. 系统环境：Windows 10 ×64
2. 程序运行环境：python 3.12
3. 涉及应用：微信**PC版**，当前项目适配的微信版本为3.9.11.25
4. 使用工具：fiddler

## 三、程序使用

### 3.1下载 / Download

- [Github / Download](https://github.com/yeximm/Access_wechat_article/archive/refs/heads/master.zip)

👆👆👆以上为本项目文件，直接clone该项目，或下载此链接均可。

### 3.2 Python环境配置

（1）创建虚拟环境

```
python -m venv venv
```

`venv`指定存放环境的目录，一般使用 `venv`，这是一个不成文的规定。

（2）激活环境

- Windows

  ```
  .\venv\Scripts\activate
  ```

- Unix/macOS

  ```
  source venv/bin/activate
  ```

（3）退出环境

```
deactivate
```

### 3.3 安装包文件

[requirements.txt](https://github.com/yeximm/Access_wechat_article/blob/master/requirements.txt)中包含所需python包文件名称，用来批量安装python包文件

安装命令：

```
pip install -r requirements.txt
```

### 3.4 运行参数

1. 项目主文件为：`main.py`，另外几个文件为功能文件，为主文件服务
   项目存储路径为：`./all_data/`（程序会自动创建）
2. 运行命令：
   - 进入项目目录后运行：`python main.py`

## 四、功能截图

### 4.1 功能1

![function1](./README/function1.png)![function1.1](./README/function1.1.png)

### 4.2 功能2

![function2](./README/function2.png)

![function2.1](./README/function2.1.png)

### 4.3 功能3

![function3](./README/function3.png)

![function3.1](./README/function3.1.png)

### 4.4 功能4

![function4](./README/function4.png)

## 五、程序流程图

![wechat_article_drawio](./README/wechat_article_drawio.png)

## 六、鼓励一下

开源不易，若此项目有帮到你，望你能动用你的发财小手**Star**☆一下。

如有遇到代码方面的问题，欢迎一起讨论，你的鼓励是这个项目继续更新的最大动力！

<p align = "center">    
<img  src="https://github.com/yeximm/Access_wechat_article/blob/master/README/qrcode_1749894334903.jpg" width="500" />
</p>

另外，十分感谢大家对于本项目的关注。

[![Stargazers repo roster for @datawhalechina/leedl-tutorial](./README/leedl-tutorial.svg+xml)](https://github.com/datawhalechina/leedl-tutorial/stargazers)
[![Forkers repo roster for @datawhalechina/leedl-tutorial](./README/leedl-tutorial-1751962216621-1.svg+xml)](https://github.com/datawhalechina/leedl-tutorial/network/members)

## 七、免责声明

所有以任何方式查看本仓库内容的人、或直接或间接使用本仓库内容的使用者都应仔细阅读此声明。本仓库管理者保留随时更改或补充此免责声明的权利。一旦使用、复制、修改了本仓库内容，则视为您已接受此免责声明。

本仓库内容中涉及的第三方硬件、软件等，与本仓库内容没有任何直接或间接的关系。本仓库内容仅对部署和使用过程进行客观描述，不代表支持使用任何第三方硬件、软件。使用任何第三方硬件、软件，所造成的一切后果由使用的个人或组织承担，与本仓库内容无关。

本项目仅供学习研究，禁止用于商业用途，所有直接或间接使用本仓库内容的个人和组织，应 24 小时内完成学习和研究，并及时删除本仓库内容。如对本仓库内容的功能有需求，应自行开发相关功能。所有基于本仓库内容的源代码，进行的任何修改，为其他个人或组织的自发行为，与本仓库内容没有任何直接或间接的关系，所造成的一切后果亦与本仓库内容和本仓库管理者无关。

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=yeximm/Access_wechat_article&type=Date)](https://www.star-history.com/#yeximm/Access_wechat_article&Date)

