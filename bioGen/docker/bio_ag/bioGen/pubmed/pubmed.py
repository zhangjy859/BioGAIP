from pymed import PubMed
import json
import tqdm
import os, tarfile, re, sys
from pypdf import PdfReader

import requests
import xml.etree.ElementTree as ET

from concurrent.futures import ThreadPoolExecutor

proxy = {
    # 'http': 'http://127.0.0.1:1083',
    # 'https': 'http://127.0.0.1:1083'
}


def convert_id(id):
    url = "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/?tool=my_tool&email=my_email@example.com&ids={id}".format(
        id=",".join([str(x) for x in id]))
    response = requests.get(url, proxies=proxy)
    xml_content = response.content
    root = ET.fromstring(xml_content)

    converted_ids = {}
    for record in root.findall('record'):
        input_id = record.get('requested-id')
        converted_id = record.get('pmcid')
        converted_ids[str(input_id)] = converted_id

    if (len(converted_ids) == 0):
        return None

    return converted_ids


def get_tgz_url(pmc_id):
    url = f"https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi?id={pmc_id}"
    response = requests.get(url, proxies=proxy)
    if response.status_code == 200:
        xml_content = response.content
        root = ET.fromstring(xml_content)

        for record in root.findall('.//record'):
            tgz_link = record.find('.//link[@format="tgz"]')
            if tgz_link is not None:
                tgz_url = tgz_link.get('href')
                return tgz_url

    return None


def download_and_extract_tgz(pmc_id, tgz_url, output_dir, skip=True):
    if tgz_url is not None:
        response = requests.get(tgz_url, proxies=proxy)
        print(response.status_code)
        if response.status_code == 200:
            if (os.path.exists(output_dir + '/' + pmc_id) and skip):
                return output_dir + '/' + pmc_id
            filename = f"{pmc_id}.tgz"
            file_path = os.path.join(output_dir, filename)
            with open(file_path, 'wb') as file:
                file.write(response.content)

            with tarfile.open(file_path, 'r:gz') as tar:
                tar.extractall(output_dir)

            return output_dir + '/' + pmc_id
            # print(f"Full text downloaded and extracted successfully: {file_path}")
        else:
            print(f"Failed to download full text for PMC ID: {pmc_id}")
    else:
        print(f"No tgz download link found for PMC ID: {pmc_id}")


def get_pdf_url(pmc_id):
    url = f"https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi?id={pmc_id}"
    response = requests.get(url, proxies=proxy)
    if response.status_code == 200:
        xml_content = response.content
        root = ET.fromstring(xml_content)

        for record in root.findall('.//record'):
            tgz_link = record.find('.//link[@format="pdf"]')
            if tgz_link is not None:
                tgz_url = tgz_link.get('href')
                return tgz_url

    return None


def download_pdf(pmc_id, pdf_url, output_dir, skip=True):
    if pdf_url is not None:
        response = requests.get(pdf_url, proxies=proxy)
        if response.status_code == 200:
            if (os.path.exists(output_dir + '/' + pmc_id + '.pdf') and skip):
                return output_dir + '/' + pmc_id + '.pdf'
            filename = f"{pmc_id}.pdf"
            file_path = os.path.join(output_dir, filename)
            with open(file_path, 'wb') as file:
                file.write(response.content)

            return output_dir + '/' + pmc_id + '.pdf'
            # print(f"Full text downloaded and extracted successfully: {file_path}")
        else:
            print(f"Failed to download full text for PMC ID: {pmc_id}")
    else:
        print(f"No pdf download link found for PMC ID: {pmc_id}")


def pdfToText(pdf_file):
    pdf = PdfReader(pdf_file)
    text = ''
    for page in pdf.pages:
        text += page.extract_text()
    return text


def math_keyword_in_artical(artical, keywords):
    # read artical as text and search for keywords
    with open(artical, 'r') as file:
        text = file.read()
        for keyword in keywords:
            if keyword in text:
                return True
    return False


class artical:
    def __init__(self, json_str):
        self.json = json_str
        self.data = json.loads(json_str)
        self.title = self.data['title']
        self.authors = self.data['authors']
        self.journal = self.data['journal']
        self.keywords = self.data['keywords']
        self.methods = self.data['methods']
        self.pubdate = self.data['publication_date']
        self.pubmed_id = self.data['pubmed_id'].split('\n')
        self.results = self.data['results']
        if self.data['doi'] is None:
            self.doi = None
        else:
            self.doi = self.data['doi'].split('\n')
        self.abstract = self.data['abstract']
        self.conclusions = self.data['conclusions']
        self.results = self.data['results']
        # self.background = self.data['background']
        self.copyrights = self.data['copyrights']

        self.pmcid = None
        self.tgzurl = None
        self.pdfurl = None
        self.article_data = None

        self.article_text = None

    def getFisrtauthor(self, key=None):
        if (len(self.authors) == 0):
            return None
        if key == 'name':
            return " ".join([str(self.authors[0]['initials']) + '.', str(self.authors[0]['lastname'])])
        if key:
            return self.authors[0][key]
        return self.authors[0]

    def getLastauthor(self, key=None):
        if (len(self.authors) == 0):
            return None
        if key == 'name':
            return " ".join([str(self.authors[-1]['initials']) + '.', str(self.authors[-1]['lastname'])])
        if key:
            return self.authors[-1][key]
        return self.authors[-1]

    def getAbstract(self):
        return self.abstract

    def getPubmedMainID(self):
        return self.pubmed_id[0]

    def getTitle(self):
        return self.title

    def getDoi(self):
        if self.doi is None:
            return None
        return self.doi[0]

    def getPulicationDate(self):
        return self.pubdate

    def getJournal(self):
        return self.journal

    def updatePMCID(self, value=None):
        if value:
            self.pmcid = value
            return self
        pubmed_id = self.getPubmedMainID()
        self.pmcid = convert_id([str(pubmed_id)])[str(pubmed_id)]
        return self

    def getPMCMainID(self):
        return self.pmcid

    def updateTgzUrl(self, value=None):
        if value:
            self.tgzurl = value
            return self
        self.tgzurl = get_tgz_url(self.pmcid)
        return self

    def getTgzUrl(self):
        return self.tgzurl

    def downloadTgz(self, output_dir):
        if self.tgzurl is None:
            _ = self.updateTgzUrl()
        if self.tgzurl is None:
            return None
        # replace ftp with https
        url = self.tgzurl.replace('ftp://', 'https://')
        self.article_data = download_and_extract_tgz(self.pmcid, url, output_dir)
        return self.article_data

    def getArticleData(self, format=None):
        if self.article_data is None:
            return None
        if not format is None:
            # list fils in data and return the matched file
            files = os.listdir(self.article_data)
            for file in files:
                if file.endswith(format):
                    return file
        return self.article_data

    def updatePdfUrl(self, value=None):
        if value:
            self.pdfurl = value
            return self
        self.pdfurl = get_pdf_url(self.pmcid)
        return self

    def getPdfUrl(self):
        return self.pdfurl

    def downloadPdf(self, output_dir):
        if self.pdfurl is None:
            _ = self.updatePdfUrl()
        if self.pdfurl is None:
            return None
        # replace ftp with https
        url = self.pdfurl.replace('ftp://', 'https://')
        self.article_data = download_pdf(self.pmcid, url, output_dir)
        return self.article_data

    def updateArticleText(self):
        if not self.article_data is None:
            self.article_text = pdfToText(self.article_data)
        return self

    def getArticleText(self):
        if self.article_text is None:
            _ = self.updateArticleText()

        if self.article_text is None:
            return None

        return self.article_text

    def __str__(self):
        str_r = "%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s" % (self.getTitle(), self.getJournal(),
                                                                self.getFisrtauthor('name'),
                                                                self.getFisrtauthor('affiliation'),
                                                                self.getLastauthor('name'),
                                                                self.getLastauthor('affiliation'), self.getAbstract(),
                                                                self.getPubmedMainID(),
                                                                self.getPulicationDate(), self.getDoi(),
                                                                self.getPMCMainID())
        # replace \n with space
        str_r = str_r.replace('\n', ' ')
        return str_r


def updatePMCID(pubmed_list):
    # all pubmed_id
    pubmed_id = [str(x.getPubmedMainID()) for x in pubmed_list]
    # print(pubmed_id)
    # convert to PMC id
    # pmcid = convert_id(pubmed_id)
    # split the pubmed_id into 100 per request and call the convert_id function then merge the result
    pmcid = {}
    for i in range(0, len(pubmed_id), 100):
        pmcid_c = convert_id(pubmed_id[i:i + 100])
        pmcid = {**pmcid, **pmcid_c}

    # update pmcid
    if len(pubmed_list) != len(pmcid):
        raise ValueError("The length of pubmed_list and pmcid is not equal.")
    for i in range(len(pubmed_list)):
        _ = pubmed_list[i].updatePMCID(pmcid[pubmed_id[i]])
    return pubmed_list


def math_text_value(text, value):
    if text is None:
        return None
    # if value is not a list convert it to a list
    if not isinstance(value, list):
        value = [value]
    status = []
    for v in value:
        if v in text:
            status.append(True)
        else:
            status.append(False)
    # if all value in the list is True return True
    if all(status):
        return True
    return False

def download_article(article_c, output_dir):
    article_c = article_c.updatePdfUrl()
    tgz_file = article_c.downloadPdf(output_dir)
    print(article_c.getPdfUrl())
    print(tgz_file)
    pdf_file = article_c.getArticleText()
    return pdf_file

if __name__ == "__main__":
    pubmed = PubMed(tool="scRNA_web", email="zhang616123@163.com")
    results = pubmed.query("Single Cell RNA-seq NOT Plants NOT Review", max_results=300)

    artical_list = [artical(article.toJSON()) for article in results]

    artical_list = updatePMCID(artical_list)

    output_dir = 'article'
    if (not os.path.exists(output_dir)):
        os.mkdir(output_dir)

    output_f = 'pymed_data.txt'

    def download_article(article_c, output_dir):
        article_c = article_c.updatePdfUrl()
        # print('downloading tgz file for article: %s' % article_c.getTitle())
        tgz_file = article_c.downloadPdf(output_dir)
        print(article_c.getPdfUrl())
        print(tgz_file)
        # print(article_c)
        pdf_file = article_c.getArticleText()
        return pdf_file

    # 创建线程池
    article_nxml = {}
    with ThreadPoolExecutor(max_workers=19) as executor:
        # 提交任务到线程池
        for article_c in artical_list:
            pubmed_id = article_c.getPubmedMainID()
            article_nxml[str(pubmed_id)] = executor.submit(download_article, article_c, output_dir).result()

    pattern1 = ['chromium', 'single cell 5']

    pattern2 = 'gel bead kit'

    pattern_match = {}
    GSE_id = {}
    for k, v in article_nxml.items():
        if v is None:
            pattern_match[k] = (None, None)
            GSE_id[k] = None
            continue
        # v to lower case
        v_text = v.lower()
        pattern1_v = False;
        pattern2_v = False
        if math_text_value(v_text, pattern1):
            pattern1_v = True
        if math_text_value(v_text, pattern2):
            pattern2_v = True
        pattern_match[k] = (pattern1_v, pattern2_v)
        v_text3 = v
        # find all the GES id in the text
        if re.search(r'GSE[0-9]{5,}', v_text3):
            GSE_id[k] = [x for x in re.findall(r'GSE[0-9]{5,}', v_text3)]
        else:
            GSE_id[k] = None

    print(pattern_match)

    output_d = open(output_f, 'w', encoding='utf-8')
    header_str = "Title\tJournal\tFirst Author\tFirst Author Affiliation\tLast Author\tLast Author Affiliation\tAbstract\tPubmed ID\tPublication Date\tDOI\tPMC ID\tPattern Match\tGSE ID\n"
    output_d.write(header_str)
    for artical_c in artical_list:
        output_str = str(artical_c)
        pubmed_id = str(artical_c.getPubmedMainID())
        pattern_match_str = str(",".join([str(x) for x in pattern_match[pubmed_id]]))
        print(GSE_id)
        if GSE_id[pubmed_id] is not None:
            GSE_id_str = str(",".join([str(x) for x in GSE_id[pubmed_id]]))
        else:
            GSE_id_str = str(None)
        output_str += '\t' + pattern_match_str + '\t' + GSE_id_str

        # print(output_str)

        output_d.write(output_str + '\n')

    output_d.close()




