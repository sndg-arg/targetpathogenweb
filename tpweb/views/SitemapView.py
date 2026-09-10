from django.http import HttpResponse
from django.urls import reverse
from django.views import View

# Only the static, public-facing content pages -- not login/admin/upload/
# BLAST (tools, not indexable content) and not dynamic per-genome/per-protein
# pages (Google finds those on its own by crawling links from genomes_list).
SITEMAP_URL_NAMES = [
    "tpwebapp:index",
    "tpwebapp:about_us",
    "tpwebapp:data_sources",
    "tpwebapp:genomes_list",
]


class SitemapView(View):
    def get(self, request, *args, **kwargs):
        urls = "\n".join(
            f"  <url><loc>{request.build_absolute_uri(reverse(name))}</loc></url>"
            for name in SITEMAP_URL_NAMES
        )
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f"{urls}\n"
            "</urlset>\n"
        )
        return HttpResponse(xml, content_type="application/xml")
