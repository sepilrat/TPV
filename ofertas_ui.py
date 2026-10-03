import os, re, sys, tempfile
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageDraw, ImageFont
from config import cfg
from repositorio import get_productos, get_categorias
import imagenes
from styles import C, F, btn, lbl, card

ROJO=(196,0,0); ROJO_OSCURO=(150,0,0); AMARILLO=(255,205,35)
BLANCO=(255,255,255); NEGRO=(25,25,25); GRIS=(105,105,105); GRIS_CLARO=(242,243,245)

def _fuente(size,bold=False):
    nombres=(['arialbd.ttf','Arial Bold.ttf','DejaVuSans-Bold.ttf'] if bold else ['arial.ttf','Arial.ttf','DejaVuSans.ttf'])
    for n in nombres:
        try:return ImageFont.truetype(n,size)
        except Exception:pass
    return ImageFont.load_default()

def _money(v): return f"$ {float(v):,.0f}".replace(',','.')

def precio_oferta(precio,descuento):
    return round(max(0,float(precio or 0))*(1-min(99,max(0,float(descuento or 0)))/100),2)

def _font_fit(draw,text,maxw,maxsize,minsize=18,bold=True):
    for size in range(maxsize,minsize-1,-2):
        f=_fuente(size,bold)
        if draw.textbbox((0,0),str(text),font=f)[2]<=maxw:return f
    return _fuente(minsize,bold)

def _center(draw,y,text,font,fill,w):
    bb=draw.textbbox((0,0),str(text),font=font)
    draw.text(((w-(bb[2]-bb[0]))/2,y),str(text),font=font,fill=fill)

def _foto(canvas,prod,box):
    x0,y0,x1,y1=box; w=x1-x0; h=y1-y0
    img=imagenes.cargar_imagen_pil(prod.get('imagen_url'))
    d=ImageDraw.Draw(canvas)
    if img is None:
        d.rounded_rectangle(box,radius=18,fill=GRIS_CLARO)
        f=_fuente(min(w,h)//9)
        _center(d,y0+h/2-15,'SIN FOTO',f,(150,150,150),w)
        return
    img=img.convert('RGB'); s=min(w/img.width,h/img.height)
    nw,nh=max(1,int(img.width*s)),max(1,int(img.height*s)); img=img.resize((nw,nh),Image.LANCZOS)
    canvas.paste(img,(x0+(w-nw)//2,y0+(h-nh)//2))

def _logo(maxw,maxh):
    p=cfg().get('negocio_logo_path')
    if not p or not os.path.isfile(p):return None
    try:
        img=Image.open(p).convert('RGBA'); s=min(maxw/img.width,maxh/img.height)
        return img.resize((max(1,int(img.width*s)),max(1,int(img.height*s))),Image.LANCZOS)
    except Exception:return None

def generar_placa_oferta(prod,descuento,formato='story',carpeta=None):
    ancho,alto={'story':(1080,1920),'cuadrado':(1080,1080)}.get(formato,(1080,1920))
    ant=float(prod.get('precio_base') or 0); nuevo=precio_oferta(ant,descuento); pad=70
    im=Image.new('RGB',(ancho,alto),BLANCO); d=ImageDraw.Draw(im)
    d.rectangle([0,0,ancho,int(alto*.25)],fill=ROJO)
    d.polygon([(0,int(alto*.25)),(int(ancho*.55),int(alto*.18)),(ancho,int(alto*.24)),(ancho,int(alto*.34)),(0,int(alto*.39))],fill=ROJO)
    logo=_logo(420,115)
    if logo: im.paste(logo,((ancho-logo.width)//2,42),logo)
    else:_center(d,52,(cfg().get('negocio_nombre') or 'AUTOSERVICIO ARAÍ').upper(),_font_fit(d,cfg().get('negocio_nombre') or 'AUTOSERVICIO ARAÍ',ancho-2*pad,55,30),BLANCO,ancho)
    _center(d,int(alto*.16),'OFERTA',_fuente(82 if formato=='story' else 70,True),BLANCO,ancho)
    cx,cy,r=ancho-205,int(alto*.275),145 if formato=='story' else 125
    d.ellipse([cx-r,cy-r,cx+r,cy+r],fill=ROJO_OSCURO,outline=BLANCO,width=8)
    _center(d,cy-45,f'-{float(descuento):g}%',_fuente(78 if formato=='story' else 68,True),BLANCO,ancho*2-410) if False else None
    f=_fuente(78 if formato=='story' else 68,True); t=f'-{float(descuento):g}%'; bb=d.textbbox((0,0),t,font=f); d.text((cx-(bb[2]-bb[0])/2,cy-(bb[3]-bb[1])/2-10),t,font=f,fill=BLANCO)
    fy=int(alto*(.30 if formato=='story' else .32)); fh=int(alto*(.35 if formato=='story' else .31))
    d.rounded_rectangle([pad,fy,ancho-pad,fy+fh],radius=30,fill=BLANCO,outline=(225,225,225),width=3)
    _foto(im,prod,(pad+35,fy+35,ancho-pad-35,fy+fh-35)); d=ImageDraw.Draw(im)
    y=fy+fh+38; nombre=(prod.get('descripcion') or '').upper()
    marca=(prod.get('marca') or '').strip().upper()
    if marca and not nombre.startswith(marca):nombre=f"{marca} {nombre}"
    fn=_font_fit(d,nombre,ancho-2*pad,55 if formato=='story' else 48,26); bb=d.textbbox((0,0),nombre,font=fn); d.text(((ancho-(bb[2]-bb[0]))/2,y),nombre,font=fn,fill=NEGRO); y+=bb[3]-bb[1]+28
    fa=_fuente(39 if formato=='story' else 34); ta=_money(ant); bb=d.textbbox((0,0),ta,font=fa); xa=(ancho-(bb[2]-bb[0]))/2; d.text((xa,y),ta,font=fa,fill=GRIS); d.line([xa-5,y+(bb[3]-bb[1])/2,xa+bb[2]-bb[0]+5,y+(bb[3]-bb[1])/2],fill=GRIS,width=3); y+=bb[3]-bb[1]+10
    tp=_money(nuevo); fp=_font_fit(d,tp,ancho-2*pad,125 if formato=='story' else 110,58); bb=d.textbbox((0,0),tp,font=fp); cw=min(ancho-2*pad,bb[2]-bb[0]+100); ch=bb[3]-bb[1]+55; x0=(ancho-cw)//2; d.rounded_rectangle([x0,y,x0+cw,y+ch],radius=28,fill=ROJO); bb=d.textbbox((0,0),tp,font=fp); d.text(((ancho-(bb[2]-bb[0]))/2,y+(ch-(bb[3]-bb[1]))/2-bb[1]),tp,font=fp,fill=BLANCO)
    py=alto-105; d.rectangle([0,py,ancho,alto],fill=ROJO); pie='   ·   '.join(x for x in (cfg().get('negocio_telefono') or '',cfg().get('negocio_direccion') or '') if x)
    if pie:_center(d,py+34,pie,_font_fit(d,pie,ancho-100,31,18),BLANCO,ancho)
    carpeta=carpeta or tempfile.gettempdir(); os.makedirs(carpeta,exist_ok=True); slug=re.sub(r'[^A-Za-z0-9]+','_',prod.get('descripcion') or 'producto').strip('_')[:50]
    ruta=os.path.join(carpeta,f'OFERTA_{slug}_{int(float(descuento))}OFF_{datetime.now():%Y%m%d_%H%M%S}.png'); im.save(ruta); return ruta

def generar_folleto_ofertas(items,titulo='OFERTAS DE LA SEMANA',vigencia=''):
    if not items:return None
    ancho,alto=1240,1754; im=Image.new('RGB',(ancho,alto),BLANCO); d=ImageDraw.Draw(im)
    d.rectangle([0,0,ancho,315],fill=ROJO); d.polygon([(0,315),(760,270),(ancho,300),(ancho,390),(0,430)],fill=ROJO)
    logo=_logo(430,100)
    if logo:im.paste(logo,((ancho-logo.width)//2,28),logo)
    _center(d,125,titulo.upper(),_font_fit(d,titulo,ancho-100,72,35),BLANCO,ancho)
    if vigencia:_center(d,220,vigencia.upper(),_font_fit(d,vigencia,ancho-100,31,18),BLANCO,ancho)
    mx,gap=48,24; cw=(ancho-2*mx-2*gap)//3; sy,rh=355,390
    for i,item in enumerate(items[:9]):
        p=item['producto']; desc=float(item['descuento']); ant=float(p.get('precio_base') or 0); nuevo=precio_oferta(ant,desc); col,row=i%3,i//3; x=mx+col*(cw+gap); y=sy+row*rh
        d.rounded_rectangle([x,y,x+cw,y+rh-gap],radius=22,fill=BLANCO,outline=(220,220,220),width=3); _foto(im,p,(x+18,y+18,x+cw-18,y+208)); d=ImageDraw.Draw(im)
        nombre=(p.get('descripcion') or '').upper();
        marca=(p.get('marca') or '').strip().upper()
        if marca and not nombre.startswith(marca):nombre=f"{marca} {nombre}"
        fn=_font_fit(d,nombre,cw-30,29,17); bb=d.textbbox((0,0),nombre,font=fn); d.text((x+(cw-(bb[2]-bb[0]))/2,y+225),nombre,font=fn,fill=NEGRO)
        ta=_money(ant); fa=_fuente(22); bb=d.textbbox((0,0),ta,font=fa); xa=x+(cw-(bb[2]-bb[0]))/2; d.text((xa,y+270),ta,font=fa,fill=GRIS); d.line([xa,y+283,xa+bb[2]-bb[0],y+283],fill=GRIS,width=2)
        tp=_money(nuevo); fp=_font_fit(d,tp,cw-28,48,28); bb=d.textbbox((0,0),tp,font=fp); pw=min(cw-20,bb[2]-bb[0]+34); px=x+(cw-pw)//2; d.rounded_rectangle([px,y+300,px+pw,y+360],radius=15,fill=ROJO); bb=d.textbbox((0,0),tp,font=fp); d.text((x+(cw-(bb[2]-bb[0]))/2,y+313),tp,font=fp,fill=BLANCO)
        d.rounded_rectangle([x+12,y+12,x+92,y+58],radius=14,fill=AMARILLO); fb=_fuente(22,True); tx=f'-{desc:g}%'; bb=d.textbbox((0,0),tx,font=fb); d.text((x+52-(bb[2]-bb[0])/2,y+20),tx,font=fb,fill=NEGRO)
    py=alto-105; d.rectangle([0,py,ancho,alto],fill=ROJO); pie='   ·   '.join(x for x in (cfg().get('negocio_telefono') or '',cfg().get('negocio_direccion') or '') if x)
    if pie:_center(d,py+35,pie,_font_fit(d,pie,ancho-80,29,17),BLANCO,ancho)
    ruta=os.path.join(tempfile.gettempdir(),f'OFERTAS_{datetime.now():%Y%m%d_%H%M%S}.png'); im.save(ruta); return ruta

class OfertasUI(ttk.Frame):
    def __init__(self,parent,app):
        super().__init__(parent); self.app=app; self._productos={}; self._productos_seleccionados={}; self._descuentos={}; self._marcados=set(); self._confirmados=set(); self._construir(); self._cargar()
    def _construir(self):
        cab=tk.Frame(self,bg=C.bg); cab.pack(fill='x',padx=12,pady=(10,4)); lbl(cab,'Generador de ofertas',variante='titulo').pack(side='left'); lbl(cab,'Seleccioná productos, aplicá descuento y generá la pieza',variante='suave').pack(side='left',padx=12)
        bar=tk.Frame(self,bg=C.bg); bar.pack(fill='x',padx=12,pady=(0,8)); lbl(bar,'Buscar:').pack(side='left'); self.buscar=tk.StringVar(); e=tk.Entry(bar,textvariable=self.buscar,width=28,font=F.normal,bg=C.superficie,fg=C.texto,relief='solid',bd=1); e.pack(side='left',padx=6,ipady=5); e.bind('<KeyRelease>',lambda _e:self._cargar())
        lbl(bar,'Categoría:').pack(side='left',padx=(12,4)); self._cats=[{'id':None,'nombre':'Todas'}]+list(get_categorias()); self.cat=tk.StringVar(value='Todas'); cb=ttk.Combobox(bar,textvariable=self.cat,width=18,state='readonly',values=[x['nombre'] for x in self._cats]); cb.pack(side='left'); cb.bind('<<ComboboxSelected>>',lambda _e:self._cargar())
        lbl(bar,'Descuento:').pack(side='left',padx=(14,4)); self.desc_general=tk.DoubleVar(value=15); tk.Spinbox(bar,from_=0,to=90,increment=1,width=5,textvariable=self.desc_general,font=F.normal).pack(side='left'); lbl(bar,'%').pack(side='left',padx=(2,8)); btn(bar,'Aplicar a seleccionados',variante='neutro',comando=self._aplicar_general).pack(side='left')
        cont=tk.Frame(self,bg=C.bg); cont.pack(fill='both',expand=True,padx=12,pady=(0,8)); cont.columnconfigure(0,weight=1); cont.rowconfigure(0,weight=1); ft=card(cont); ft.grid(row=0,column=0,sticky='nsew'); ft.columnconfigure(0,weight=1); ft.rowconfigure(0,weight=1)
        cols=('sel','producto','precio','desc','oferta'); self.tree=ttk.Treeview(ft,columns=cols,show='headings',selectmode='extended')
        for cid,txt,w,anc in (('sel','',36,'center'),('producto','Producto',360,'w'),('precio','Precio',100,'e'),('desc','Desc. %',90,'e'),('oferta','Oferta',110,'e')): self.tree.heading(cid,text=txt); self.tree.column(cid,width=w,anchor=anc,minwidth=30)
        sb=ttk.Scrollbar(ft,orient='vertical',command=self.tree.yview); self.tree.configure(yscrollcommand=sb.set); self.tree.grid(row=0,column=0,sticky='nsew'); sb.grid(row=0,column=1,sticky='ns'); self.tree.bind('<Button-1>',self._click_fila)
        panel=tk.Frame(cont,bg=C.bg); panel.grid(row=0,column=1,sticky='ns',padx=(12,0)); lbl(panel,'Producto seleccionado',variante='subtitulo').pack(anchor='w'); self.lbl_sel=lbl(panel,'Ninguno',variante='suave'); self.lbl_sel.pack(anchor='w',pady=(2,8)); lbl(panel,'Descuento individual:').pack(anchor='w'); self.desc_ind=tk.DoubleVar(value=15); tk.Spinbox(panel,from_=0,to=90,increment=1,width=7,textvariable=self.desc_ind,font=F.normal).pack(anchor='w',pady=4); btn(panel,'Aplicar al seleccionado',comando=self._aplicar_ind).pack(fill='x',pady=(0,12)); btn(panel,'Marcar visibles',variante='neutro',comando=self._marcar_visibles).pack(fill='x'); btn(panel,'Desmarcar todo',variante='neutro',comando=self._desmarcar).pack(fill='x',pady=4); btn(panel,'CONFIRMAR SELECCIÓN',variante='exito',comando=self._confirmar).pack(fill='x',pady=(10,4)); self.lbl_confirm=lbl(panel,'Sin selección confirmada',variante='suave'); self.lbl_confirm.pack(anchor='w',pady=(2,0))
        out=tk.Frame(self,bg=C.bg); out.pack(fill='x',padx=12,pady=(0,12)); lbl(out,'Título:').pack(side='left'); self.titulo=tk.StringVar(value='OFERTAS DE LA SEMANA'); tk.Entry(out,textvariable=self.titulo,width=27,font=F.normal).pack(side='left',padx=5,ipady=4); lbl(out,'Vigencia:').pack(side='left',padx=(10,4)); self.vigencia=tk.StringVar(); tk.Entry(out,textvariable=self.vigencia,width=24,font=F.normal).pack(side='left',ipady=4); btn(out,'GENERAR FOLLETO 3×3',variante='exito',comando=self._folleto).pack(side='right',padx=(5,0)); btn(out,'GENERAR PLACA',variante='exito',comando=lambda:self._individual('cuadrado')).pack(side='right',padx=5); btn(out,'Story',variante='neutro',comando=lambda:self._individual('story')).pack(side='right')
    def _cargar(self):
        filtro=self.buscar.get().strip(); cid=self._cats[[x['nombre'] for x in self._cats].index(self.cat.get())]['id']; self._productos={p['codigo']:p for p in get_productos(filtro=filtro,categoria_id=cid)}
        for code,p in self._productos.items():
            if code not in self._descuentos:self._descuentos[code]=float(self.desc_general.get() or 0)
        for iid in self.tree.get_children():self.tree.delete(iid)
        for code,p in self._productos.items():
            d=self._descuentos[code]; marca='✓' if code in self._marcados else ''; self.tree.insert('','end',iid=code,values=(marca,p['descripcion'],_money(p['precio_base']),f'{d:g}',_money(precio_oferta(p['precio_base'],d))))
        self._actualizar_estado()

    def _click_fila(self,event):
        iid=self.tree.identify_row(event.y)
        if not iid:return
        self.tree.selection_set(iid)
        self._toggle(iid)

    def _toggle(self,iid):
        if iid in self._marcados:
            self._marcados.discard(iid)
        else:
            self._marcados.add(iid); self._productos_seleccionados[iid]=self._productos[iid]
        if iid in self._marcados and iid not in self._descuentos:self._descuentos[iid]=float(self.desc_general.get() or 0)
        if iid in self.tree.get_children():
            v=list(self.tree.item(iid,'values')); v[0]='✓' if iid in self._marcados else ''; self.tree.item(iid,values=v)
        self._confirmados.clear(); self._actualizar_estado('Selección modificada: volvé a confirmar')

    def _sel(self):return [i for i in self.tree.get_children() if i in self._marcados]
    def _aplicar_general(self):
        if not self._marcados:
            messagebox.showinfo('Ofertas','Marcá al menos un producto.',parent=self); return
        d=float(self.desc_general.get() or 0)
        for i in list(self._marcados):
            self._descuentos[i]=min(90,max(0,d))
            if i in self.tree.get_children():self._set_desc(i,d)
        self._confirmados.clear(); self._actualizar_estado('Descuentos modificados: volvé a confirmar')
    def _aplicar_ind(self):
        s=self.tree.selection()
        if not s:messagebox.showinfo('Ofertas','Seleccioná una fila primero.',parent=self);return
        self._set_desc(s[0],float(self.desc_ind.get() or 0))
    def _set_desc(self,iid,d):
        d=min(90,max(0,d)); self._descuentos[iid]=d
        if iid in self.tree.get_children():
            v=list(self.tree.item(iid,'values')); v[3]=f'{d:g}'; v[4]=_money(precio_oferta(self._productos[iid]['precio_base'],d)); self.tree.item(iid,values=v)
        self._confirmados.clear(); self._actualizar_estado('Descuentos modificados: volvé a confirmar')
    def _marcar_visibles(self):
        for i in self.tree.get_children():
            self._marcados.add(i); self._productos_seleccionados[i]=self._productos[i]; v=list(self.tree.item(i,'values')); v[0]='✓'; self.tree.item(i,values=v)
        self._confirmados.clear(); self._actualizar_estado('Selección modificada: volvé a confirmar')
    def _desmarcar(self):
        self._marcados.clear(); self._productos_seleccionados.clear()
        for i in self.tree.get_children():v=list(self.tree.item(i,'values'));v[0]='';self.tree.item(i,values=v)
        self._confirmados.clear(); self._actualizar_estado('Sin selección confirmada')
    def _actualizar_estado(self,text=None):
        if text is not None:self.lbl_confirm.config(text=text); return
        if self._confirmados:self.lbl_confirm.config(text=f'✓ {len(self._confirmados)} producto(s) confirmado(s)')
        elif self._marcados:self.lbl_confirm.config(text=f'{len(self._marcados)} producto(s) marcado(s) — falta confirmar')
        else:self.lbl_confirm.config(text='Sin selección confirmada')

    def _confirmar(self):
        ids=set(self._marcados)
        if not ids:
            messagebox.showinfo('Ofertas','Marcá al menos un producto para confirmar la selección.',parent=self); return
        self._confirmados=ids
        self._actualizar_estado()
        messagebox.showinfo('Selección confirmada',f'Se confirmaron {len(ids)} producto(s).\n\nAhora usá GENERAR PLACA o GENERAR FOLLETO 3×3.',parent=self)

    def _items(self):
        if not self._confirmados:return []
        return [{'producto':self._productos_seleccionados[i],'descuento':self._descuentos.get(i,0)} for i in self._confirmados if i in self._productos_seleccionados]
    def _abrir(self,ruta):
        if not ruta:return
        try:
            if sys.platform=='win32':os.startfile(ruta)
            elif sys.platform=='darwin':os.system(f'open "{ruta}"')
            else:os.system(f'xdg-open "{ruta}" >/dev/null 2>&1')
        except Exception:pass
        messagebox.showinfo('Oferta generada',f'Archivo generado:\n\n{ruta}',parent=self)
    def _individual(self,formato):
        items=self._items()
        if not items:messagebox.showinfo('Ofertas','Seleccioná al menos un producto.',parent=self);return
        if len(items)>1:
            messagebox.showinfo('Ofertas','La placa individual corresponde a un solo producto.\n\nTenés varios seleccionados; usá GENERAR FOLLETO 3×3 o dejá marcado solamente uno.',parent=self); return
        self._abrir(generar_placa_oferta(items[0]['producto'],items[0]['descuento'],formato))
    def _folleto(self):
        items=self._items()
        if not items:messagebox.showinfo('Ofertas','Seleccioná al menos un producto.',parent=self);return
        self._abrir(generar_folleto_ofertas(items,self.titulo.get(),self.vigencia.get()))
    def refrescar(self):self._cargar()

def abrir_generador_ofertas(parent):
    d=tk.Toplevel(parent)
    d.title('Generador de ofertas')
    d.configure(bg=C.bg)
    d.geometry(f'{min(1180,d.winfo_screenwidth()-60)}x{min(720,d.winfo_screenheight()-80)}')
    d.minsize(900,560)
    OfertasUI(d, getattr(parent,'app',None)).pack(fill='both',expand=True)
